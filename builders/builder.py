#!/usr/bin/env python
'''
Description: This will build all the applets in the HiSeq4000_bcl2fastq workflow.
    For this pilot workflow, the only applet built will be bcl2fastq
Args: -t dxapp.template
Retuns: bcl2fastq applet, dxid of workflow object,
'''

import os
import sys
import pdb
import dxpy
import json
import stat
import shutil
import logging
import argparse
import datetime
import subprocess

from dxpy import app_builder

class WorkflowBuild:

    def __init__(self, name, path_list, internal_rsc_manager, external_rsc_manager):

        self.workflow_name = name
        self.workflow_logger = configure_logger(name = self.workflow_name, 
                                                object_type = 'BuildWorkflow',
                                                path_list = path_list
                                                )
        self.applet_logger = configure_logger(name = self.workflow_name, 
                                              object_type = 'Applet',
                                              path_list = path_list
                                              )
        path_list = PathList()
        
        self.environment = self.parse_environment(path_list = path_list)
        self.project_key = self.environment['project_key']
        self.project_dxid = self.environment['project_dxid']
        self.branch = self.environment['git_branch']
        self.current_version = self.environment['version']

        # Logic for choosing applet path in DXProject; used by Applet:write_config_file()
        if self.project_key == 'develop':
            self.workflow_dxpath = os.path.join('/', 
                                                self.current_version, 
                                                self.branch,
                                                self.workflow_name
                                                )
        else:
            self.workflow_dxpath = os.path.join('/', self.current_version, self.workflow_name)
        self.workflow_logger.info('Workflow path on DNAnexus will be: %s:%s' % (self.project_dxid, self.workflow_dxpath))

        # Load workflow configuration object
        workflow_config = WorkflowConfig(path_list = path_list, 
                                         project_dxid = self.project_dxid,
                                         name = self.workflow_name
                                         )

        # Build all applets listed in workflow
        for applet_name in workflow_config.applets:
            self.workflow_logger.info('Building %s applet' % applet_name)
            applet = Applet(name = applet_name, 
                            version = self.current_version, 
                            path_list = path_list,
                            logger = self.applet_logger
                            )
            self.workflow_logger.info('Applet initialized')
            internal_rscs = workflow_config.applets[applet_name]['internal_rscs']
            internal_rsc_manager.add_applet_internal_rscs(applet=applet, 
                                                          internal_rscs=internal_rscs, 
                                                          )
            external_rscs = workflow_config.applets[applet_name]['external_rscs']
            external_rsc_manager.add_applet_external_rscs(applet=applet, 
                                                          external_rscs=external_rscs
                                                          )
            applet.write_config_file(project_dxid = self.project_dxid)
            applet_id = applet.build(project_dxid = self.project_dxid,
                                     folder_path = self.workflow_dxpath)
            workflow_config.applets[applet_name]['dxid'] = applet_id['id']
            self.workflow_logger.info('Build complete: %s applet id: %s' % (applet_name, applet_id))
        
        # Create workflow 
        workflow_properties = {
                               'name': self.workflow_name,
                               'branch': self.branch, 
                               'version': self.current_version,
                               'date_created': str(datetime.datetime.now()).split()[0] # yyyy-mm-dd
                              }
        workflow_config.create_workflow(path=self.workflow_dxpath, properties=workflow_properties)
        for stage_index in range(0, len(workflow_config.stages)):
            self.workflow_logger.info('Setting executable for stage %d' % stage_index)
            workflow_config.set_stage_executable(str(stage_index))

        for stage_index in range(0, len(workflow_config.stages)):
            self.workflow_logger.info('Setting inputs for stage %d' % stage_index)
            workflow_config.set_stage_inputs(str(stage_index))
        
        workflow_config.update_config_file(path_list)
        self.workflow_logger.info('Build complete: %s workflow id: {%s, %s}' % (self.workflow_name, 
                                                                       workflow_config.project_dxid,
                                                                       workflow_config.object_dxid
                                                                       ))

    def parse_environment(self, path_list):
        ''' Description: First, reads in the possible build-environment 
        configurations currently supported, from the configuration 
        file: build_workflow.json. Then, determines the appropriate
        environment, based on the git branch. Returns dict with current
        build environment information.
        '''

        # Parse builer.json           
        with open(path_list.build_json, 'r') as CONFIG:
            build_config = json.load(CONFIG)

        # Get the current github branch, commit, and the latest version tag        
        git_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).rstrip()
        git_commit = subprocess.check_output(['git', 'describe', '--always']).rstrip()
        git_tag = subprocess.check_output(['git', 'describe', '--abbrev=0']).rstrip()
        version = git_tag.split('v')[1] 

        git_branch_base = git_branch.split('_')[0]
        #pdb.set_trace()
        if git_branch_base == 'master':
            project_dxid = build_config['workflow_projects']['production']['dxid']
            project_key = 'production'
        elif git_branch_base in ['develop', 'feature', 'release']:
            project_dxid = build_config['workflow_projects']['develop']['dxid']
            project_key = 'develop'
        elif git_branch_base == 'hotfix':
            project_dxid = build_config['workflow_projects']['hotfix']['dxid']
            project_key = 'hotfix'
        else:
            self.workflow_logger.critical('Could not determine DXProject for branch: %s' % git_branch)
            sys.exit()

        environment = {
                       'project_key': project_key,
                       'project_dxid': project_dxid,
                       'external_rscs_dxid': build_config['external_rscs_project']['dxid'],
                       'git_branch': git_branch,
                       'git_commit': git_commit,
                       'version': version
                      }
        return environment

class WorkflowConfig:

    def __init__(self, path_list, project_dxid, name):
        ''' Dev: Eventually only rebuild applets/workflows if the applet source
                 has changed.
        '''

        self.name = name
        self.project_dxid = project_dxid

        workflow_json_basename = self.name + '.json'
        self.config_path = os.path.join(path_list.workflow_config_templates, 
                                            workflow_json_basename
                                            )

        self.logger = configure_logger(name = self.name, 
                               object_type = 'WorkflowConfig',
                               path_list = path_list
                               )
        
        self.new_workflow = True    # Always building new applets/workflows, now

        self.attributes = None
        self.object = None
        self.object_dxid = None
        self.edit_version = None
        self.dx_OS = None           # Not in use

        self.stages = {}
        self.applets = {}

        ## Get workflow attributes - should be part of __init__ I think
        self.dx_login_check()
        self.get_workflow_attributes()

        if not self.project_dxid and not self.object_dxid:
            self.project_dxid = self.create_new_workflow_project()

    def dx_login_check(self):
        try:
            dxpy.api.system_whoami()
        except:
            logger.error('You must login to DNAnexus before proceeding ($ dx login)')
            sys.exit()

    def create_new_workflow_project(self):

        project_dxid = dxpy.api.project_new(input_params={'name' : self.name})['id']
        return project_dxid

    def get_workflow_attributes(self):
        
        with open(self.config_path, 'r') as CONFIG:
            self.attributes = json.load(CONFIG)
            
        self.edit_version = self.attributes['edit_version']
        self.dx_OS = self.attributes['dx_OS']

        self.applets = self.attributes['applets']
        self.stages = self.attributes['stages']

    def create_workflow(self, path, properties):
        #if self.object_dxid:
        if self.new_workflow == False:
            self.object = dxpy.DXWorkflow(self.object_dxid)
        #elif not self.object_dxid:
        elif self.new_workflow == True:
            self.object = dxpy.new_dxworkflow(title = self.name,
                                              name =  self.name,
                                              project = self.project_dxid,
                                              folder = path,
                                              properties = properties
                                              )
            self.object_dxid = self.object.describe()['id']

    def set_stage_executable(self, stage_index):
        #pdb.set_trace()
        self.edit_version = self.object.describe()['editVersion']
        
        #if self.stages[stage_index]['dxid']:
        if self.new_workflow == False:
            output_folder = self.stages[stage_index]['folder']
            applet_name = self.stages[stage_index]['executable']
            applet_dxid = self.applets[applet_name]['dxid']
            self.object.update_stage(stage = stage_index,
                                     edit_version = self.edit_version, 
                                     executable = applet_dxid, 
                                     folder = output_folder
                                    )
        
        #elif not self.stages[stage_index]['dxid']:
        elif self.new_workflow == True:
            output_folder = self.stages[stage_index]['folder']
            applet_name = self.stages[stage_index]['executable']
            applet_dxid = self.applets[applet_name]['dxid']
            stage_dxid = self.object.add_stage(edit_version = self.edit_version,
                                               executable = applet_dxid,
                                               folder = output_folder
                                              )
            self.stages[stage_index]['dxid'] = stage_dxid

    def set_stage_inputs(self, stage_index):
        if not self.stages[stage_index]['dxid']:
            logger.error('Stage %s has not yet been created' % stage_index)
        stage_input = {}

        standard_inputs = self.stages[stage_index]['input']
        for name in standard_inputs:
            if name == 'applet_build_version':
                version_label = self.get_version_label()
                self.stages[stage_index]['input']['applet_build_version'] = version_label
                stage_input[name] = version_label
            elif name == 'applet_project':
                self.stages[stage_index]['input']['applet_project'] = self.project_dxid
                stage_input[name] = self.project_dxid

        linked_inputs = self.stages[stage_index]['linked_input']
        ## DEV: Change linked input from dict to LIST of dicts. 
        ##      If length of linked_input == 1 stage_input = dict (as is)
        ##      Elif length of linked_input > 1 stage_input = list
        ##          append input of dicts
        for field_name in linked_inputs:
            linked_input = linked_inputs[field_name]
            if type(linked_input) is dict:
                field_type = linked_input['field']
                input_stage_index = linked_input['stage']
                input_stage_dxid = self.stages[input_stage_index]['dxid']
                stage_input[field_name] = {'$dnanexus_link': {
                                                              'stage': input_stage_dxid,
                                                              field_type: field_name
                                                             }
                                          }
            elif type(linked_input) is list:
                stage_input[field_name] = []
                for list_input in linked_input:
                    #pdb.set_trace()
                    field_type = list_input['field']
                    input_stage_index = list_input['stage']
                    input_stage_dxid = self.stages[input_stage_index]['dxid']
                    stage_input[field_name].append({'$dnanexus_link': {
                                                                  'stage': input_stage_dxid,
                                                                  field_type: field_name
                                                                 }
                                                    })
            #print 'Info: Stage %d field %s input:' % (int(stage_index), field_name)
            #print stage_input
        self.edit_version = self.object.describe()['editVersion']
        self.object.update_stage(stage = stage_index,
                                 edit_version = self.edit_version,
                                 stage_input = stage_input
                                )

    def update_config_file(self, path_list):
        ''' Description: Open workflow config file, get 'date_created' value,
                         and rename to 'external_rscs_<date_created>.json'
        '''
        
        # Check if there is an existing configuration file and archive it
        existing_config_path = self.config_path
        basename = os.path.basename(existing_config_path)
        name_elements = basename.split('.')
        filename = name_elements[0]
        filetype = name_elements[1]
        if os.path.isfile(existing_config_path):
            with open(existing_config_path, 'r') as EXIST:
                existing_json = json.load(EXIST)
            existing_date_created = existing_json['date_created']
            existing_config_archived = '%s_%s.%s' % (filename, 
                                                     existing_date_created, 
                                                     filetype)
            existing_config_archived_path = os.path.join(path_list.workflow_config_templates, 'archive',
                                                         existing_config_archived)
            os.rename(existing_config_path, existing_config_archived_path)
        
        # Create new JSON file
        self.attributes['date_created'] = str(datetime.datetime.now()).split()[0] # yyyy-mm-dd
        self.attributes['edit_version'] = self.edit_version

        with open(self.config_path, 'w') as CONFIG:
            json.dump(self.attributes, CONFIG, sort_keys=True, indent=4)

    def get_version_label(self):
        timestamp = str(datetime.datetime.now()).split()[0] # yyyy-mm-dd
        current_commit = self._get_git_commit().rstrip()
        version_label = '%s_%s' % (timestamp, current_commit)
        return version_label

    def _get_git_commit(self):
        # NOTE: not at all confident this is optimal solution
        commit = subprocess.check_output(['git', 'describe', '--always'])
        return commit 

class AppletBuild:

    def __init__(self, name, path_list, internal_rsc_manager, external_rsc_manager):

        self.logger = configure_logger(name = name, 
                                       object_type = 'applet',
                                       path_list = path_list
                                       )
        
        self.environment = self.parse_environment(path_list = path_list)
        self.project_key = self.environment['project_key']
        self.project_dxid = self.environment['project_dxid']
        self.branch = self.environment['git_branch']
        self.current_version = self.environment['version']

        # Logic for choosing applet path in DXProject; used by Applet:write_config_file()
        if self.project_key == 'develop':
            self.applet_dxpath = os.path.join('/', self.current_version, self.branch)
        else:
            self.applet_dxpath = os.path.join('/', self.current_version)
        self.logger.info('Applet path on DNAnexus will be: %s' % self.applet_dxpath)

        # Create resource managers
        self.logger.info('Creating resource managers')
        internal_rsc_manager = InternalRscsManager(path_list.internal_rscs_json, path_list)
        external_rscs_project_dxid = self.environment['external_rscs_dxid']
        external_rsc_manager = ExternalRscsManager(external_rscs_project_dxid, path_list)

        # Load applet resources JSON
        self.logger.info('Loading applet resources config file: %s' % path_list.applet_rscs)
        with open(path_list.applet_rscs, 'r') as JSON:
            applet_rscs = json.load(JSON)

        # Start assembling applet
        self.logger.info('Assembling applet %s locally' % self.applet_name)
        self.applet = Applet(name = self.applet_name, 
                             version = self.current_version,
                             path_list = path_list
                             )
        
        self.logger.info('Adding applet resources')
        try:
            internal_rscs = applet_rscs[self.applet_name]['internal_rscs']
            external_rscs = applet_rscs[self.applet_name]['external_rscs']
        except:
            self.logger.critical('Could not find internal or external resources ' +
                                 'listed for applet: %s ' % self.applet_name + 
                                 'in %s' % path_list.applet_rscs
                                 )
            sys.exit()
        internal_rsc_manager.add_applet_internal_rscs(applet = self.applet, 
                                                      internal_rscs = internal_rscs 
                                                      )
        external_rsc_manager.add_applet_external_rscs(applet= self.applet, 
                                                      external_rscs = external_rscs
                                                      )

        self.applet.write_config_file(project_dxid = self.project_dxid)
        applet_id = self.applet.build(project_dxid = self.project_dxid, 
                                      folder_path = self.applet_dxpath
                                      )
        self.logger.info('Build complete: %s applet id: %s' % (self.applet_name, applet_id))

    def parse_environment(self, path_list):
        ''' Description: First, reads in the possible build-environment 
        configurations currently supported, from the configuration 
        file: build_workflow.json. Then, determines the appropriate
        environment, based on the git branch. Returns dict with current
        build environment information.
        '''

        # Parse builer.json           
        with open(path_list.build_json, 'r') as CONFIG:
            build_config = json.load(CONFIG)

        # Get the current github branch, commit, and the latest version tag        
        git_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).rstrip()
        git_commit = subprocess.check_output(['git', 'describe', '--always']).rstrip()
        git_tag = subprocess.check_output(['git', 'describe', '--abbrev=0']).rstrip()
        version = git_tag.split('v')[1] 

        git_branch_base = git_branch.split('_')[0]
        #pdb.set_trace()
        if git_branch_base == 'master':
            project_dxid = build_config['applet_projects']['production']['dxid']
            project_key = 'production'
        elif git_branch_base in ['develop', 'feature', 'release']:
            project_dxid = build_config['applet_projects']['develop']['dxid']
            project_key = 'develop'
        elif git_branch_base == 'hotfix':
            project_dxid = build_config['applet_projects']['hotfix']['dxid']
            project_key = 'hotfix'
        else:
            self.logger.critical('Could not determine DXProject for branch: %s' % git_branch)
            sys.exit()

        environment = {
                       'project_key': project_key,
                       'project_dxid': project_dxid,
                       'external_rscs_dxid': build_config['external_rscs_project']['dxid'],
                       'git_branch': git_branch,
                       'git_commit': git_commit,
                       'version': version
                      }
        return environment

class Applet:

    def __init__(self, name, version, path_list, logger=None):
        
        self.name = name
        self.version = version
        if logger:
            self.logger = logger
        else:
            self.logger = configure_logger(name = self.name, 
                                           object_type = 'Applet',
                                           path_list = path_list
                                           )
        # DEV: Think I'm going to deprecate version_label; moving to project/folder model
        self.version_label = self.get_version_label()
        
        self.internal_rscs = []     # Filled by self.add_rsc()
        self.bundled_depends = []   # External resources
        # List of dictionaries: [{'filename':<filename>, 'dxid':<dxid>}, {...}, ...]

        ## Find applet code
        ## DEV: Change this to dynamically search for files with prefix matching name
        matching_files = []
        for source_file in os.listdir(path_list.applets_source):
            if source_file.startswith(self.name):
                matching_files.append(source_file)
            else:
                pass
        print matching_files

        if len(matching_files) == 1:
            code_basename = matching_files[0]
            self.logger.info('Found source file for %s: %s' % (self.name, code_basename))
        elif len(matching_files) == 0:
            self.logger.error('Could not find source file for %s' % self.name)
            sys.exit()
        elif len(matching_files) > 1: 
            self.logger.error('Found multiple source files for %s' % self.name)
            print matching_files
            sys.exit()

        self.code_path = os.path.join(path_list.applets_source, code_basename)
        # Find applet configuration file
        config_basename = self.name + '.template.json'
        self.config_path = os.path.join(path_list.applet_templates, config_basename)
        
        # Make applet directory structure because it is necessary for adding internal rscs
        # All directories are made in 'home' directory, which should usually be base of repo
        self.applet_path = '%s/%s/%s' % (path_list.launchpad, self.name, self.version_label)
        self.src_path = '%s/%s/%s/src' % (path_list.launchpad, self.name, self.version_label)
        self.rscs_path = '%s/%s/%s/resources' % (path_list.launchpad, self.name, self.version_label) 

        self._make_new_dir(self.src_path)
        self._make_new_dir(self.rscs_path)

        # Copy source code into applet directory
        shutil.copy(self.code_path, '%s/%s' % (self.src_path, code_basename))

    def build(self, project_dxid, folder_path, dry_run=False):
        '''
        Build the applet on DNAnexus
        '''
        
        # Create new build folder if does not already exist
        dx_project = dxpy.DXProject(dxid=project_dxid)
        dx_project.new_folder(folder=folder_path, parents=True)

        # Upload applet to DNAnexus
        dxpy.app_builder.upload_applet(src_dir = self.applet_path, 
                                       uploaded_resources = None, 
                                       project = project_dxid, 
                                       overwrite = True, 
                                       override_folder = folder_path, 
                                       override_name = self.name
                                      )

        # Get dxid of newly built applet
        applet_dict = dxpy.find_one_data_object(name = self.name, 
                                                project = project_dxid, 
                                                folder = folder_path, 
                                                zero_ok = False, 
                                                more_ok = False
                                               )
        return applet_dict

    def add_rsc(self, local_path, dnanexus_path):
        '''
        Internal rscs are locally stored and are added to an applet by
        copying them into the applet/rsc directory. rscs are added to
        the root directory of the virtual machine instance at runtime.

        Arguments:
            local_rsc_path : string ; full local path of rsc file to be added to applet
            dnanexus_path : string ; relative path to where rsc file should be unpacked on DNAnexus
                (default is root directory)
        Returns:
        '''
        
        local_path = local_path
        dnanexus_path = dnanexus_path
        applet_path = self.rscs_path + dnanexus_path
        
        # Create parent directories within applet
        rsc_dirname = os.path.dirname(applet_path)
        if not os.path.exists(rsc_dirname):
            os.makedirs(rsc_dirname)

        if (os.path.isfile(local_path)):
            shutil.copyfile(local_path, applet_path)
            self.internal_rscs.append(local_path)
        else:
            self.logger.error('Could not find internal applet rsc file: %s' % local_path)
            sys.exit() 

    def add_bundledDepends(self, filename, dxid):
        '''
        External rscs are stored and compiled remotely on DNAnexus and
        are added to an applet by specifying their DNAnexus file information
        in the bundledDepends attribute of runSpec in the configuration file.
        '''

        bundled_depends_dict = {'filename': filename, 'dxid': dxid}
        self.bundled_depends.append(bundled_depends_dict)

    def write_config_file(self, project_dxid, out_file='dxapp.json'):
        '''
        <Blurb about static vs dynamic attributes etc.>
        '''

        out_path = '%s/%s' % (self.applet_path, out_file)
        
        # Load static configuration attributes from template file
        with open(self.config_path, 'r') as TEMPLATE:
            config_attributes = json.load(TEMPLATE)

        # Update config_attributes with folder and version information
        config_attributes['version'] = self.version
        
        # Create blank dxapp.json file to allow for 'upload_resources'
        with open(out_path, 'w') as DXAPP:
            DXAPP.write('temporary file')

        ## Set new values for dynamic configuration attributes
        for external_rsc in self.bundled_depends:
            filename = external_rsc['filename']
            dxid = external_rsc['dxid']
            dependency_dict = {"name" : filename, "id" : {'$dnanexus_link':dxid}}
            config_attributes['runSpec']['bundledDepends'].append(dependency_dict)

        ## Dump configuration attributes into new 'dxapp.json' file
        with open(out_path, 'w') as OUT:
            json.dump(config_attributes, OUT, sort_keys=True, indent=4)

        # If applet has internal resources, upload them and add to config file
        # DEV: I don't understand how this works.
        if len(self.internal_rscs) > 0:
            #pdb.set_trace()
            rscs_links = dxpy.app_builder.upload_resources(src_dir = self.applet_path, 
                                                           project = project_dxid, 
                                                           folder = '/')
            config_attributes['runSpec']['bundledDepends'].append(rscs_links[0])
            with open(out_path, 'w') as OUT:
                json.dump(config_attributes, OUT, sort_keys=True, indent=4)
        else:
            self.logger.info('No internal resources uploaded for applet %s' % self.name)

    ## Private functions
    def _make_new_dir(self, directory):
        if not os.path.exists(directory):
            os.makedirs(directory)

    def _get_git_commit(self):
        # NOTE: not at all confident this is optimal solution
        commit = subprocess.check_output(['git', 'describe', '--always'])
        return commit 

    def get_version_label(self):
        timestamp = str(datetime.datetime.now()).split()[0] # yyyy-mm-dd
        current_commit = self._get_git_commit().rstrip()
        version_label = '%s_%s' % (timestamp, current_commit)
        return version_label

class ExternalRscManager:

    def __init__(self, path_list, project_dxid, os="Ubuntu-12.04", name='external_resources.json'):
        self.local_dir = path_list.external_rscs

        with open(path_list.external_rscs_json, 'r') as EXTERNAL_RSC_CONFIG:
            self.config = json.load(EXTERNAL_RSC_CONFIG)

        self.project_dxid = project_dxid
        self.filename = name
        self.basename = self.filename.split('.')[0]
        self.file_type = self.filename.split('.')[1]
        self.os = os
        self.dx_os = '/' + self.os  # All dnanexus paths must begin with '/'
        
        self.config_data = None
    
    def update(self):
        # Open local 'external_rscs.json', get 'date_created' value,
        # and rename to 'external_rscs_<date_created>.json'
        
        # Check if there is an existing configuration file and archive it
        existing_config_dir = os.path.join(self.local_dir, self.os)
        if not os.path.exists(existing_config_dir):
            os.makedirs(existing_config_dir)

        existing_config_path = os.path.join(self.local_dir, self.os, self.filename)
        if os.path.isfile(existing_config_path):
            with open(existing_config_path, 'r') as EXIST:
                existing_json = json.load(EXIST)
            existing_date_created = existing_json['date_created']
            existing_config_archived = '%s_%s.%s' % (self.basename, 
                                                     existing_date_created, 
                                                     self.file_type
                                                    )
            existing_config_archived_path = os.path.join(self.local_dir, self.os, existing_config_archived)
            os.rename(existing_config_path, existing_config_archived_path)
        
        # Get dxid of remote external rscs configuration file
        updated_config_dxlink = dxpy.find_one_data_object(zero_ok=False, more_ok=False,
            name=self.filename, project=self.project_dxid, folder=self.dx_os)
        updated_config_dxid = updated_config_dxlink['id']
        # Download updated version of external rscs configuration file
        updated_config_path = os.path.join(self.local_dir, self.os, self.filename) 
        dxpy.download_dxfile(dxid=updated_config_dxid, filename=updated_config_path, project=self.project_dxid)

    def load_config_data(self):
        config_path = os.path.join(self.local_dir, self.os, self.filename)

        if self.file_type == 'json':
            with open(config_path, 'r') as CONFIG:
                self.config_data = json.load(CONFIG)
        else:
            print 'Error: Unrecognized configuration file rsc_type: %s for configuration file: %s' % (self.file_type, self.filename)
            sys.exit()

    def get_filename_dxid(self, name, version=None):
        '''
        Returns: Dictionary object of format {'filename':<filename>, 'dxid':<dxid>}
        '''
        # Automatically load configuration data if not already done
        if not self.config_data:
            self.load_config_data()
        # If no version specified, get current one
        if not version:
            rsc_filename = self.config_data[name]['filename']
            rsc_dxid = self.config.data[name]['dxid']
        elif version:
            try:
                rsc_filename = self.config_data[name]['versions'][version]['filename']
                rsc_dxid = self.config_data[name]['versions'][version]['dxid']
            except:
                print 'Error: Could not get external rsc information for %s version %s' % (name, version)
        resouce_dict = {'filename':rsc_filename, 'dxid':rsc_dxid}
        return(rsc_dict)

    def add_rsc_to_applet(self, applet, name, version=None):
        # Check that configuration data has been loaded
        if not self.config_data:
            self.load_config_data()

        if version:
            filename = self.config_data[name]['versions'][version]['filename']
            dxid = self.config_data[name]['versions'][version]['dxid']
        elif not version:
            filename = self.config_data[name]['filename']
            dxid = self.config_data[name]['dxid']
        applet.add_bundledDepends(filename, dxid)

    def add_applet_external_rscs(self, applet, external_rscs):
        ## Add applet external rscs to configuration file   
        for rsc in external_rscs:
            if 'version' in rsc:
                name = rsc['name']
                version = rsc['version']
                self.add_rsc_to_applet(applet, name, version)
            elif not 'version' in rsc:
                name = rsc['name']
                self.add_rsc_to_applet(applet, name)
            else:
                print 'How did you get here?'
                sys.exit()

class InternalRscManager:
    ''' 
    Instead of having InternalResourceManager get the paths, have it handle
    all the aspects of adding rscs to the applet
        InternalrscManager.add_rsc_to_applet(applet, rsc_type, name, internal_rscs_path)
    
    DEV: I think I should hardcode more of this stuff to make it fixed, rather
    than trying to weave it through Workflow -> Stage objects. trajectoread
    represents a mix of dynamic static architecture.
    '''

    def __init__(self, path_list):
        self.internal_rscs_path = path_list.internal_rscs
        with open(path_list.internal_rscs_json, 'r') as INTERNAL_RSC_CONFIG:
            self.config = json.load(INTERNAL_RSC_CONFIG)

    def add_applet_internal_rscs(self, applet, internal_rscs):
        for rsc_type in internal_rscs:
            for rsc_name in internal_rscs[rsc_type]:
                self.add_rsc_to_applet(applet, rsc_type, rsc_name)

    def add_rsc_to_applet(self, applet, rsc_type, name):
        if rsc_type == 'python_packages':
            self._add_python_package(applet, rsc_type, name)
        else:
            local_path = self._get_local_path(rsc_type, name)
            dnanexus_path = self._get_dnanexus_path(rsc_type, name)
            applet.add_rsc(local_path, dnanexus_path)

    def _add_python_package(self, applet, rsc_type, name):
        print 'Info: Adding python package %s to applet' % name
        package_files = self.config[rsc_type][name]["all_files"]
        for file in package_files:
            file_local_path = self._get_local_path(rsc_type, name) + '/' + file
            file_dnanexus_path = self._get_dnanexus_path(rsc_type, name) + '/' + file
            applet.add_rsc(file_local_path, file_dnanexus_path)

    def _get_local_path(self, rsc_type, name):
        relative_path = self.config[rsc_type][name]["local_path"]
        full_path = self.internal_rscs_path + '/' + relative_path
        if (os.path.exists(full_path)):
            return full_path
        else:
            print 'Error: Could not find internal rsc path:' + full_path
            sys.exit()

    def _get_dnanexus_path(self, rsc_type, name):
        path_name = self.config[rsc_type][name]["dnanexus_location"]
        path = self.config["dnanexus_path"][path_name]["path"]
        full_path = path + '/' + name
        return full_path

class PathList:

    def __init__(self):
        self.builders = os.path.dirname(os.path.abspath(__file__))
        self.home = os.path.split(self.builders)[0]
        self.dnanexus_os = 'Ubuntu-12.04'
        
        # Specify relative directory paths. Depends on 'self.home'
        self.applets_source = os.path.join(self.home, 'applets_source')
        self.external_rscs = os.path.join(self.home, 'external_resources')
        self.internal_rscs = os.path.join(self.home, 'internal_resources')
        self.applet_templates = os.path.join(self.home, 'applet_config_templates')
        self.workflow_config_templates = os.path.join(self.home, 'workflow_config_templates')
        self.launchpad = os.path.join(self.home, 'launchpad')
        self.logs = os.path.join(self.builders, 'logs')
        
        # Specify relative file paths.
        self.build_json = os.path.join(self.builders, 'builder.json')
        self.applet_rscs = os.path.join(self.builders, 'applet_resources.json')
        self.internal_rscs_json = os.path.join(self.internal_rscs, 'internal_resources.json')
        self.external_rscs_json = os.path.join(self.external_rscs,
                                               self.dnanexus_os,
                                               'external_resources.json'
                                               )
    
    def update_dnanexus_os(self, dnanexus_os):
        self.dnanexus_os = dnanexus_os
        self.external_rscs_json = os.path.join(self.external_rscs, 
                                               self.dnanexus_os, 
                                               'external_resources.json'
                                              )
    def describe(self):
        self.__dict__

def configure_logger(name, object_type, path_list):
    # Configure Logger object
    logger = logging.getLogger(object_type)    # Create logger object
    logger.setLevel(logging.DEBUG)

    timestamp = str(datetime.datetime.now()).split()[0]     # yyyy-mm-dd
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Add logging file handler
    file_handler_basename = 'builder_%s_%s_%s.log' % (name, object_type, timestamp)
    file_handler_path = os.path.join(path_list.logs, file_handler_basename)
    LOG = logging.FileHandler(file_handler_path)
    LOG.setLevel(logging.DEBUG)
    LOG.setFormatter(formatter)
    logger.addHandler(LOG)

    # Add logging stream handler
    STREAM = logging.StreamHandler(sys.stdout)
    STREAM.setLevel(logging.DEBUG)
    STREAM.setFormatter(formatter)
    logger.addHandler(STREAM)

    return logger

def main():

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--applet_name', dest='applet_name', type=str)
    parser.add_argument('-w', '--workflow_name', dest='workflow_name', type=str)
    args = parser.parse_args()
    print args
    if args.applet_name and args.workflow_name:
        # temporary logger stand-in
        print 'Error: applet and workflow arguments passed to builder. Can only build one object at once'
        sys.exit()    
    elif not args.applet_name and not args.workflow_name:
        print 'Error: no valid DNAnexus objects specified for building'
        sys.exit()

    # Initiate path list and global resource manager objects
    path_list = PathList()
    
    # Read 'builder.json' configuration file for building workflows/applets
    with open(path_list.build_json, 'r') as build_json:
        build_config = json.load(build_json)
    dnanexus_os = build_config['dnanexus_os']
    path_list.update_dnanexus_os(dnanexus_os)

    internal_rsc_manager = InternalRscManager(path_list)
    external_rsc_manager = ExternalRscManager(path_list,
                                              build_config['external_rscs_project'],
                                              dnanexus_os
                                              )

    # Create build object
    if args.applet_name:
        print 'Building applet: %s' % args.applet_name
        builder = AppletBuild(name = args.applet_name, 
                              path_list = path_list,
                              internal_rsc_manager = internal_rsc_manager,
                              external_rsc_manager = external_rsc_manager
                              )
    elif args.workflow_name:
        print 'Building workflow: %s' % args.workflow_name
        builder = WorkflowBuild(name = args.workflow_name, 
                                path_list = path_list,
                                internal_rsc_manager = internal_rsc_manager,
                                external_rsc_manager = external_rsc_manager
                                )

        
if __name__ == "__main__":
    main() 
