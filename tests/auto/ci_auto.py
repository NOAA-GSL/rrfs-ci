"""
Revising this Python program to use for WE2E testing. It is based on:
Automation of UFS Regression Testing for ufs-weather-model

Oct 2022 - adding code to also automate GSI regression tests

This script automates the process of UFS CI for
code managers at NOAA-EMC

This script should be started through start_ci_py_pro.sh so that
env vars and Python paths are set up prior to start.
"""
from github import Github as gh

import datetime
import subprocess
import re
import os
import logging
from configparser import ConfigParser as config_parser
import importlib


class GHInterface:
    '''
    This class stores information for communicating with GitHub
    ...

    Attributes
    ----------
    GHACCESSTOKEN : str
      API token to authenticate with GitHub
    client : pyGitHub communication object
      The connection to GitHub to make API requests
    '''

    def __init__(self):
        self.logger = logging.getLogger('GHINTERFACE')

        filename = 'accesstoken'

        if os.path.exists(filename):
            if oct(os.stat(filename).st_mode)[-3:] != 600:
                with open(filename) as f:
                    os.environ['ghapitoken'] = f.readline().strip('\n')
            else:
                raise Exception('File permission needs to be "600" ')
        else:
            raise FileNotFoundError('Cannot find file "accesstoken"')

        try:
            self.client = gh(os.getenv('ghapitoken'))
        except Exception as e:
            self.logger.critical(f'Exception is {e}')
            raise (e)


def set_action_from_label(machine, actions, label):
    ''' Match the label that initiates a job with an action in the dict
        Labels have a ci- prefix'''
    # ci-<machine>-<compiler>-<test> i.e. ci-hera-intel-build
    logger = logging.getLogger('MATCH_LABEL_WITH_ACTIONS')
    # split the label apart and remove its prefix
    split_label = label.name.split('-')[1:]
    # Make sure it has three parts
    if len(split_label) != 3:
        return False, False
    # Break out the label parts
    label_machine, label_compiler, label_action = split_label
    # check machine name matches
    if not re.match(label_machine, machine):
        return False, False
    # Compiler must be intel or gnu
    if not str(label_compiler) in ["intel", "gnu"]:
        return False, False
    logger.info(f'Setting action from Label {label}')
    action_match = next((action for action in actions
                         if re.match(action, label_action)), False)

    return label_compiler, action_match


def get_preqs_with_actions(repos, machine_dict, ghinterface_obj, actions):
    ''' Create list of dictionaries of a pull request
        and its machine label and action '''
    logger = logging.getLogger('GET_PREQS_WITH_ACTIONS')
    logger.info('Getting Pull Requests with Actions')
    jobs = []
    for repo in repos:
        gh_preqs = [ghinterface_obj.client.get_repo(repo['address'])
                                   .get_pulls(state='open', sort='created',
                                              base=repo['base'])]

        each_pr = [preq for gh_preq in gh_preqs for preq in gh_preq]
        preq_labels = [{'preq': pr, 'label': label} for pr in each_pr
                       for label in pr.get_labels()]

        for pr_label in preq_labels:
            compiler, match = set_action_from_label(machine_dict['machine'],
                                                    actions, pr_label['label'])
            if match:
                pr_label['action'] = match
                jobs.append(Job(pr_label.copy(), ghinterface_obj,
                                machine_dict, compiler, repo))

    return jobs


class Job:
    '''
    This class stores all information needed to run jobs on this machine.
    This class provides all methods needed to run all jobs.
    ...

    Attributes
    ----------
    preq_dict: dict
        Dictionary of all data that comes from the GitHub pull request
    ghinterface_obj: object
        An interface to GitHub setup through class GHInterface
    machine: dict
        Information about the machine the jobs will be running on
        provided by the bash script
    '''

    def __init__(self, preq_dict, ghinterface_obj, machine_dict, compiler,
                 repo):
        self.logger = logging.getLogger('JOB')
        self.preq_dict = preq_dict
        # both SRWA build and WE2E tests call same module build.py
        # GSI regression tests call regr.py

        # Weather Model can call rt or bl (UC in tag, lc in program name)
        if self.preq_dict["action"] == "rt":
            self.job_mod = importlib.import_module('jobs.regr')
        elif self.preq_dict["action"] == "BL":
            self.job_mod = importlib.import_module('jobs.bl')
        elif self.preq_dict["action"] == "RT":
            self.job_mod = importlib.import_module('jobs.rt')
        else:
            self.job_mod = importlib.import_module('jobs.build')
        self.ghinterface_obj = ghinterface_obj
        self.machine = machine_dict['machine']
        self.compiler = compiler
        self.repo = repo
        self.hpc_acc = machine_dict['hpc_acc']
        self.workdir = machine_dict['workdir']
        self.comment_text = ''
        self.failed_tests = []

    def comment_append(self, newtext):
        self.comment_text += f'{newtext}\n'

    def remove_pr_label(self):
        ''' Removes the PR label that initiated the job run from PR '''
        self.logger.info(f'Removing Label: {self.preq_dict["label"]}')
        self.preq_dict['preq'].remove_from_labels(self.preq_dict['label'])

    def check_label_before_job_start(self):
        # LETS Check the label still exists before the start of the job in the
        # case of multiple jobs
        label_to_check = f'ci-{self.machine}'\
                         f'-{self.compiler}'\
                         f'-{self.preq_dict["action"]}'
        labels = self.preq_dict['preq'].get_labels()
        label_match = next((label for label in labels
                            if re.match(label.name, label_to_check)), False)

        return label_match

    def run_commands(self, logger, commands_with_cwd):
        for command, in_cwd in commands_with_cwd:
            logger.info(f'Running `{command}`')
            logger.info(f'in location "{in_cwd}"')
            try:
                output = subprocess.Popen(command, shell=True, cwd=in_cwd,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT)
            except Exception as e:
                self.job_failed(logger, 'subprocess.Popen', exception=e)
            else:
                try:
                    out, err = output.communicate()
                    out = [] if not out else out.decode('utf8').split('\n')
                    logger.info(out)
                    if output.returncode != 0:
                        err_msg = "Nonzero returncode: " + str(output.returncode)
                        raise Exception(err_msg)
                except Exception as e:
                    err = [] if not err else err.decode('utf8').split('\n')
                    self.job_failed(logger, f'Command {command}', exception=e,
                                    STDOUT=True, out=out, err=err)
                else:
                    logger.info(f'Finished running: {command}')

    def run(self):
        logger = logging.getLogger('JOB/RUN')
        logger.info(f'Starting Job: {self.preq_dict["label"]}')
        self.comment_append(newtext=f'Machine: {self.machine}')
        self.comment_append(f'Compiler: {self.compiler}')
        self.comment_append(f'Job: {self.preq_dict["action"]}')
        if self.check_label_before_job_start():
            try:
                logger.info('Calling remove_pr_label')
                self.remove_pr_label()
                logger.info('Calling Job to Run')
                self.job_mod.run(self)
            except Exception:
                self.job_failed(logger, 'run()')
                logger.info('Sending comment text')
                issue_id = self.send_comment_text()
                logger.debug(f'Issue comment id is {issue_id}')
        else:
            logger.info(f'Cannot find label {self.preq_dict["label"]}')

    def send_comment_text(self):
        logger = logging.getLogger('JOB/SEND_COMMENT_TEXT')
        logger.info(f'Comment Text: {self.comment_text}')
        self.comment_append('If test failed, please make changes and add '
                            'the following label back:')
        self.comment_append(f'ci-{self.machine}'
                            f'-{self.compiler}'
                            f'-{self.preq_dict["action"]}')

        issue_id = \
            self.preq_dict['preq'].create_issue_comment(self.comment_text)
        return (issue_id)

    def job_failed(self, logger, job_name, exception=Exception, STDOUT=False,
                   out=None, err=None):
        logger.critical(f'{job_name} FAILED. Exception:{exception}')

        if STDOUT:
            logger.critical(f'STDOUT: {[item for item in out if not None]}')
            logger.critical(f'STDERR: {[eitem for eitem in err if not None]}')


def setup_env():
    logger = logging.getLogger('SETUP')

    config = config_parser()

    # Pull machine specific values from a config file
    # Only very specific values will work - see docs

    file_name = 'CImachine.cfg'
    if not os.path.exists(file_name):
        logger.info(f'Could not find {file_name}')
        raise KeyError(f'Machine config file {file_name} '
                       'not found. Exiting.')
    else:
        machine_dict = {}
        config.read(file_name)
        machine_dict['machine'] = config['DEFAULT']['machine']
        machine_dict['hpc_acc'] = config['DEFAULT']['hpc_acc']
        machine_dict['workdir'] = config['DEFAULT']['workdir']

    if not os.path.exists(machine_dict['workdir']):
        raise KeyError(f'Work directory from config file '
                       f'{machine_dict["workdir"]} not found. Exiting.')

    # Build dictionary of GitHub repositories to check
    # from config file. Workflow repo matched to app repo

    file_name = 'CIrepos.cfg'
    if not os.path.exists(file_name):
        logger.info(f'Could not find {file_name}')
        raise KeyError(f'Repo config file {file_name} '
                       'not found. Exiting.')
    else:
        repo_dict = []
        config.read(file_name)
        for ci_repo in config.sections():
            one_repo = {
                'name': config[ci_repo]['base_name'],
                'address': config[ci_repo]['base_address'],
                'base': config[ci_repo]['base_branch'],
                'app_name': config[ci_repo]['app_name'],
                'app_address': config[ci_repo]['app_address'],
                'app_branch': config[ci_repo]['app_branch']
            }
            repo_dict.append(one_repo)

    # Approved Actions

    action_list = ['build', 'WE', 'rt', 'BL', 'RT']

    return machine_dict, repo_dict, action_list


def main():

    # handle logging
    log_filename = f'ci_auto_'\
                   f'{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.log'
    logging.basicConfig(filename=log_filename, filemode='w',
                        level=logging.INFO)
    logger = logging.getLogger('MAIN')
    logger.info('Starting Script')

    # setup environment
    logger.info('Getting the environment setup')
    machine_dict, repos, actions = setup_env()

    # setup interface with GitHub
    logger.info('Setting up GitHub interface.')
    ghinterface_obj = GHInterface()

    # get all pull requests from the GitHub object
    # and turn them into Job objects
    logger.info('Getting all pull requests, '
                'labels and actions applicable to this machine.')
    jobs = get_preqs_with_actions(repos, machine_dict,
                                  ghinterface_obj, actions)
    [job.run() for job in jobs]

    logger.info('Script Finished')


if __name__ == '__main__':
    main()
