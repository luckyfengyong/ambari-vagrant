"""
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Ambari Agent

"""

import os
import tempfile
import shutil

from resource_management.core.providers.package import PackageProvider
from resource_management.core import shell
from resource_management.core.shell import string_cmd_from_args_list
from resource_management.core.logger import Logger

INSTALL_CMD_ENV = {'DEBIAN_FRONTEND':'noninteractive'}
INSTALL_CMD = {
  True: ['/usr/bin/apt-get', '-o', "Dpkg::Options::=--force-confdef", '-o', "Dpkg::Options::=--force-overwrite", '--allow-unauthenticated', '--assume-yes', 'install'],
  False: ['/usr/bin/apt-get', '-q', '-o', "Dpkg::Options::=--force-confdef", '-o', "Dpkg::Options::=--force-overwrite", '--allow-unauthenticated', '--assume-yes', 'install'],
}
REMOVE_CMD = {
  True: ['/usr/bin/apt-get', '-y', 'remove'],
  False: ['/usr/bin/apt-get', '-y', '-q', 'remove'],
}
REPO_UPDATE_CMD = ['/usr/bin/apt-get', 'update','-qq']

CHECK_EXISTENCE_CMD = "dpkg --get-selections | grep -v deinstall | awk '{print $1}' | grep '^%s$'"
GET_PACKAGES_BY_PATTERN_CMD = "apt-cache --names-only search '^%s$' | awk '{print $1}'"
GET_PACKAGE_STATUS_CMD = "dpkg --status '%s'"

PACKAGE_INSTALLED_STATUS = 'Status: install ok installed'

EMPTY_FILE = "/dev/null"
APT_SOURCES_LIST_DIR = "/etc/apt/sources.list.d"

def replace_underscores(function_to_decorate):
  def wrapper(*args):
    self = args[0]
    name = args[1].replace("_", "-")
    return function_to_decorate(self, name, *args[2:])
  return wrapper


class AptProvider(PackageProvider):

  @replace_underscores
  def install_package(self, name, use_repos=[]):
    if not self._check_existence(name) or use_repos:
      cmd = INSTALL_CMD[self.get_logoutput()]
      copied_sources_files = []
      is_tmp_dir_created = False
      if use_repos:
        is_tmp_dir_created = True
        apt_sources_list_tmp_dir = tempfile.mkdtemp(suffix="-ambari-apt-sources-d")
        Logger.info("Temporal sources directory was created: %s" % apt_sources_list_tmp_dir)
        if 'base' not in use_repos:
          cmd = cmd + ['-o', 'Dir::Etc::SourceList=%s' % EMPTY_FILE]
        for repo in use_repos:
          if repo != 'base':
            new_sources_file = os.path.join(apt_sources_list_tmp_dir, repo + '.list')
            Logger.info("Temporal sources file will be copied: %s" % new_sources_file)
            shutil.copy(os.path.join(APT_SOURCES_LIST_DIR, repo + '.list'), new_sources_file)
            copied_sources_files.append(new_sources_file)
        cmd = cmd + ['-o', 'Dir::Etc::SourceParts=%s' % apt_sources_list_tmp_dir]

      cmd = cmd + [name]
      Logger.info("Installing package %s ('%s')" % (name, string_cmd_from_args_list(cmd)))
      code, out = shell.call(cmd, sudo=True, env=INSTALL_CMD_ENV, logoutput=self.get_logoutput())
      
      # apt-get update wasn't done too long
      if code:
        Logger.info("Execution of '%s' returned %d. %s" % (cmd, code, out))
        Logger.info("Failed to install package %s. Executing `%s`" % (name, string_cmd_from_args_list(REPO_UPDATE_CMD)))
        code, out = shell.call(REPO_UPDATE_CMD, sudo=True, logoutput=self.get_logoutput())
        
        if code:
          Logger.info("Execution of '%s' returned %d. %s" % (REPO_UPDATE_CMD, code, out))
          
        Logger.info("Retrying to install package %s" % (name))
        shell.checked_call(cmd, sudo=True, logoutput=self.get_logoutput())

      if is_tmp_dir_created:
        for temporal_sources_file in copied_sources_files:
          Logger.info("Removing temporal sources file: %s" % temporal_sources_file)
          os.remove(temporal_sources_file)
        Logger.info("Removing temporal sources directory: %s" % apt_sources_list_tmp_dir)
        os.rmdir(apt_sources_list_tmp_dir)
    else:
      Logger.info("Skipping installing existent package %s" % (name))

  @replace_underscores
  def upgrade_package(self, name, use_repos=[]):
    return self.install_package(name, use_repos)

  @replace_underscores
  def remove_package(self, name):
    if self._check_existence(name):
      cmd = REMOVE_CMD[self.get_logoutput()] + [name]
      Logger.info("Removing package %s ('%s')" % (name, string_cmd_from_args_list(cmd)))
      shell.checked_call(cmd, sudo=True, logoutput=self.get_logoutput())
    else:
      Logger.info("Skipping removing non-existent package %s" % (name))

  @replace_underscores
  def _check_existence(self, name):
    code, out = shell.call(CHECK_EXISTENCE_CMD % name)
    if bool(code):
      return False
    elif '*' in name or '.' in name:  # Check if all packages matching regexp are installed
      code1, out1 = shell.call(GET_PACKAGES_BY_PATTERN_CMD % name)
      for package_name in out1.splitlines():
        code2, out2 = shell.call(GET_PACKAGE_STATUS_CMD % package_name)
        if PACKAGE_INSTALLED_STATUS not in out2.splitlines():
          return False
      return True
    else:
      return True
