#!/usr/bin/env python
# tar_files 0.0.1
# Generated by dx-app-wizard.
#
# Basic execution pattern: Your app will run on a single machine from
# beginning to end.
#
# See https://wiki.dnanexus.com/Developer-Portal for documentation and
# tutorials on how to modify this file.
#
# DNAnexus Python Bindings (dxpy) documentation:
#   http://autodoc.dnanexus.com/bindings/python/current/

import os
import multiprocessing
import subprocess
import dxpy

WORK_DIR = 'work'

class FlowcellLane:

    def __init__(self, project_dxid, record_dxid, dashboard_project_dxid):
        if record_dxid and dashboard_project_dxid:
            # If a record is provided; name tarball according to 'SCGPM_'
            self.record = dxpy.DXRecord(dxid=record_dxid, project=dashboard_project_dxid)

            # Values gotten from DXRecord
            self.flowcell_id = None
            self.run_name = None
            self.run_date = None
            self.lane_index = None
            self.library_name = None
            self.project_dxid = None
        elif project_dxid:
            # If not, just give it the project name
            self.project_dxid = project_dxid
            self.project = dxpy.DXProject(dxid=self.project_dxid)
            self.run_name = self.project.describe()['name']
            self.record = None
        else:
            print ERROR_NO_INPUT

        if self.record:            
            self.parse_record_properties()
            self.parse_record_details()

    def parse_record_properties(self):
        self.properties = self.record.get_properties()
        
        self.flowcell_id = self.properties['flowcell_id']

    def parse_record_details(self):
        self.details = self.record.get_details()
        
        self.project_dxid = self.details['laneProject']
        
        library_label = self.details['library']
        elements = library_label.split('rcvd')
        library_name = elements[0].rstrip()
        library_name = library_name.replace(' ', '-')
        library_name = library_name.replace('_', '-')
        library_name = library_name.replace('.', '-')
        self.library_name = library_name

        self.lane_index = int(self.details['lane'])
        self.run_name = self.details['run']
        self.run_date = self.run_name.split('_')[0]

    def download_files_by_pattern(self, folder, names, name_mode):

        for name in names:
            dxlink_generator = dxpy.find_data_objects(classname = 'file',
                                                      name = name,
                                                      name_mode = name_mode, 
                                                      project = self.project_dxid,
                                                      folder = '/'
                                                     )
            dxlink_list = list(dxlink_generator)
            if len(dxlink_list) > 0:
                try:
                    os.mkdir(folder)
                except:
                    print 'Folder %s already exists. Skipping mkdir' % folder
                os.chdir(folder)

                for dxlink in dxlink_list:
                    print dxlink
                    file_handler = dxpy.get_handler(id_or_link = dxlink['id'],
                                                    project = dxlink['project']
                                                   )
                    filename = file_handler.name
                    
                    dxpy.download_dxfile(dxid = dxlink['id'], 
                                         filename = filename,
                                         project = dxlink['project']
                                        )
                os.chdir('../')

    def get_tar_name(self):

        if self.record:
            tar_name = 'SCGPM_%s_%s_%s_L%d.tar' % (self.run_date,
                                                   self.library_name, 
                                                   self.flowcell_id,
                                                   self.lane_index 
                                                  )
        else:
            tar_name = '%s.tar' % self.run_name
        return tar_name


def run_command(cmd, returnOutput = False):
    print cmd
    if returnOutput:
        output = subprocess.check_output(cmd, shell=True, executable='/bin/bash')
        print output
        return output
    else:
        subprocess.check_call(cmd, shell=True, executable='/bin/bash')

@dxpy.entry_point('main')
def main(project_dxid=None, project_name=None, record_dxid=None, dashboard_project_dxid=None):
    
    output = {}

    lane = FlowcellLane(project_dxid, record_dxid, dashboard_project_dxid)
    tarball_name = lane.get_tar_name()

    home = os.getcwd()
    tar_dir = tarball_name.split('.')[0]
    tar_path = os.path.join(home, tar_dir)
    
    os.mkdir(tar_path)
    os.chdir(tar_path)

    # Download all fastq files into subfolder 'fastqs'
    lane.download_files_by_pattern(folder = 'fastqs', 
                                   names = ['*.fastq.gz', '*.fastq'], 
                                   name_mode = 'glob'
                                  )
    # Download all bam files and indexes into subfolder 'bams'
    lane.download_files_by_pattern(folder = 'bams',
                                   names = ['*.bam', '*.bai'],
                                   name_mode = 'glob'
                                  )
    # Download all fastqc reports into 'fastqc_reports'
    lane.download_files_by_pattern(folder = 'fastqc_reports',
                                   names = ['*_fastqc_*'],
                                   name_mode = 'glob'
                                  )
    # Download QC Report into root of directory to be tarred
    lane.download_files_by_pattern(folder = '.',
                                   names = ['*_QC_Report.pdf'],
                                   name_mode = 'glob'
                                  )
    os.chdir(home)
    
    tar_command = 'tar -zcvf %s %s' % (tarball_name, tar_dir)

    print 'Info: creating tar archive: %s' % tarball_name
    run_command(tar_command)
    output['tarball'] = dxpy.dxlink(dxpy.upload_local_file(tarball_name))
    return(output)

dxpy.run()
























