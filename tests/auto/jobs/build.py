# Imports
import datetime
import logging
import time
import os
from configparser import ConfigParser as config_parser


def run(job_obj):
    """
    Runs a CI test for a PR
    """
    logger = logging.getLogger('BUILD/RUN')
    workdir = set_directories(job_obj)
    pr_repo_loc, repo_dir_str = clone_pr_repo(job_obj, workdir)
    # Setting this for the test/build.sh script
    os.environ['SR_WX_APP_TOP_DIR'] = pr_repo_loc
    build_script_loc = pr_repo_loc + '/test'
    log_name = 'build.out'
    create_build_commands = [[f'./build.sh {job_obj.machine} >& {log_name}',
                             build_script_loc]]
    logger.info('Running test build script')
    job_obj.run_commands(logger, create_build_commands)
    # Read the build log to see whether it succeeded
    build_success = post_process(job_obj, build_script_loc, log_name)
    logger.info('After build post-processing')
    logger.info(f'Action: {job_obj.preq_dict["action"]}')
    if build_success:
        job_obj.comment_append('Build was Successful')
        if job_obj.preq_dict["action"] == 'WE':
            logger.info('Running end to end test')
            expt_script_loc = pr_repo_loc + '/regional_workflow/tests/WE2E'
            expt_dirs = repo_dir_str + '/expt_dirs'
            log_name = 'expt.out'
            create_expt_commands = \
                [[f'./end_to_end_tests.sh {job_obj.machine} zrtrr >& '
                 f'{log_name}', expt_script_loc]]
            job_obj.run_commands(logger, create_expt_commands)
            logger.info('After end_to_end script')
            if os.path.exists(expt_dirs):
                job_obj.comment_append('Rocoto jobs started')
                process_expt(job_obj, expt_dirs)
            else:
                gen_log_loc = pr_repo_loc + '/regional_workflow/ush'
                gen_log_name = 'log.generate_FV3LAM_wflow'
                process_gen(job_obj, gen_log_loc, gen_log_name)
    else:
        job_obj.comment_append('Build Failed')
    job_obj.send_comment_text()


def set_directories(job_obj):
    """
    Set up work directory for various hpc machines
    """
    logger = logging.getLogger('BUILD/SET_DIRECTORIES')
    if job_obj.machine == 'hera':
        workdir = '/scratch2/BMC/zrtrr/rrfs_ci/autoci/pr'

    elif job_obj.machine == 'jet':
        workdir = '/lfs1/BMC/nrtrr/rrfs_ci/autoci/pr'

    elif job_obj.machine == 'gaea':
        workdir = '/lustre/f2/pdata/ncep/emc.nemspara/autort/pr'

    elif job_obj.machine == 'orion':
        workdir = '/work/noaa/nems/emc.nemspara/autort/pr'

    elif job_obj.machine == 'cheyenne':
        workdir = '/glade/scratch/dtcufsrt/autort/tests/auto/pr'

    else:
        logger.critical(f'Machine {job_obj.machine} id '
                        'not supported for this job')
        raise KeyError

    logger.info(f'machine: {job_obj.machine}')
    logger.info(f'workdir: {workdir}')

    return workdir


def run_regression_test(job_obj, pr_repo_loc):
    logger = logging.getLogger('BUILD/RUN_REGRESSION_TEST')
    if job_obj.compiler == 'gnu':
        rt_command = [[f'export RT_COMPILER="{job_obj.compiler}" && cd tests '
                       '&& /bin/bash --login ./rt.sh -e -c -l rt_gnu.conf',
                       pr_repo_loc]]
    elif job_obj.compiler == 'intel':
        rt_command = [[f'export RT_COMPILER="{job_obj.compiler}" && cd tests '
                       '&& /bin/bash --login ./rt.sh -e -c', pr_repo_loc]]
    job_obj.run_commands(logger, rt_command)


def remove_pr_data(job_obj, pr_repo_loc, repo_dir_str, rt_dir):
    logger = logging.getLogger('BUILD/REMOVE_PR_DATA')
    rm_command = [
                 [f'rm -rf {rt_dir}', pr_repo_loc],
                 [f'rm -rf {repo_dir_str}', pr_repo_loc]
                 ]
    job_obj.run_commands(logger, rm_command)


def clone_pr_repo(job_obj, workdir):
    ''' clone the GitHub pull request repo, via command line '''
    logger = logging.getLogger('BUILD/CLONE_PR_REPO')
    repo_name = job_obj.repo["app_address"]
    branch = job_obj.repo["app_branch"]
    git_url = f'https://${{ghapitoken}}@github.com/{repo_name}'
    logger.info(f'GIT URL: {git_url}')
    logger.info(f'app branch: {branch}')
    logger.info('Starting repo clone')
    repo_dir_str = f'{workdir}/'\
                   f'{str(job_obj.preq_dict["preq"].id)}/'\
                   f'{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}'
    pr_repo_loc = f'{repo_dir_str}/ufs-srweather-app'
    job_obj.comment_append(f'Repo location: {pr_repo_loc}')

    create_repo_commands = [
        [f'mkdir -p "{repo_dir_str}"', os.getcwd()],
        [f'git clone -b {branch} {git_url}', repo_dir_str]]
    job_obj.run_commands(logger, create_repo_commands)

    # Set up configparser to read and update Externals.cfg ini/config file
    # to change one repo to match the head of the code in the PR
    config = config_parser()
    file_name = 'Externals.cfg'
    file_path = os.path.join(pr_repo_loc, file_name)
    if not os.path.exists(file_path):
        logger.info('Could not find Externals.cfg')
    else:
        config.read(file_path)
        updated_section = job_obj.preq_dict['preq'].head.repo.name
        logger.info(f'updated section: {updated_section}')
        new_repo = "https://github.com/" + \
            job_obj.preq_dict['preq'].head.repo.full_name
        logger.info(f'new repo: {new_repo}')

        if config.has_section(updated_section):

            config.set(updated_section, 'hash',
                       job_obj.preq_dict['preq'].head.sha)
            config.set(updated_section, 'repo_url', new_repo)
            # Can only have one of hash, branch, tag
            if config.has_option(updated_section, 'branch'):
                config.remove_option(updated_section, 'branch')
            if config.has_option(updated_section, 'tag'):
                config.remove_option(updated_section, 'tag')
            # open existing Externals.cfg to update it
            with open(file_path, 'w') as fname:
                config.write(fname)
        else:
            logger.info('No section {updated_section} in Externals.cfg')

    # call manage externals with new Externals.cfg to get other repos
    logger.info('Starting manage externals')
    create_repo_commands = [['./manage_externals/checkout_externals',
                             pr_repo_loc]]

    job_obj.run_commands(logger, create_repo_commands)

    logger.info('Finished repo clone')
    return pr_repo_loc, repo_dir_str


def post_process(job_obj, build_script_loc, log_name):
    logger = logging.getLogger('BUILD/POST_PROCESS')
    ci_log = f'{build_script_loc}/{log_name}'
    logfile_pass = process_logfile(job_obj, ci_log)
    logger.info('Log file was processed')
    logger.info(f'Status of build: {logfile_pass}')

    return logfile_pass


def process_logfile(job_obj, ci_log):
    """
    Runs after code has been cloned and built
    Checks to see whether build was successful or failed
    """
    logger = logging.getLogger('BUILD/PROCESS_LOGFILE')
    fail_string = 'FAIL'
    build_failed = False
    if os.path.exists(ci_log):
        with open(ci_log) as fname:
            for line in fname:
                if fail_string in line:
                    build_failed = True
                    job_obj.comment_append(f'{line.rstrip()}')
        if build_failed:
            job_obj.send_comment_text()
            logger.info('Build failed')
        else:
            logger.info('Build was successful')
        return not build_failed
    else:
        logger.critical(f'Could not find {job_obj.machine}'
                        f'.{job_obj.compiler} '
                        f'{job_obj.preq_dict["action"]} log')
        raise FileNotFoundError


def process_gen(job_obj, gen_log_loc, gen_log_name):
    """
    Runs after a rocoto workflow has been generated
    Checks to see if an error has occurred
    """
    logger = logging.getLogger('BUILD/PROCESS_GEN')
    gen_log = f'{gen_log_loc}/{gen_log_name}'
    error_string = 'ERROR'
    gen_failed = False
    if os.path.exists(gen_log):
        with open(gen_log) as fname:
            for line in fname:
                if error_string in line:
                    job_obj.comment_append('Generating Workflow Failed')
                    gen_failed = True
                    logger.info('Generating workflow failed')
                if gen_failed:
                    job_obj.comment_append(f'{line.rstrip()}')


def process_expt(job_obj, expt_dirs):
    """
    Runs after a rocoto workflow has been started to run one or more expts
    Assumes that more expt directories can appear after this job has started
    Checks for success or failure for each expt
    """
    logger = logging.getLogger('BUILD/PROCESS_EXPT')
    expt_done = 0
    repeat_count = 72
    complete_expts = []
    expt_list = []
    complete_string = "This cycle is complete"
    failed_string = "FAILED"

    while not expt_done and repeat_count > 0:
        time.sleep(300)
        repeat_count = repeat_count - 1
        expt_done = 0
        expt_list = os.listdir(expt_dirs)
        logger.info('Experiment dir after return of end_to_end')
        logger.info(expt_list)
        for expt in expt_list:
            expt_log = expt_dirs + '/' + expt + \
                '/log/FV3LAM_wflow.log'
            if os.path.exists(expt_log) and expt not in complete_expts:
                with open(expt_log) as fname:
                    for line in fname:
                        if complete_string in line:
                            expt_done = expt_done + 1
                            job_obj.comment_append(f'Experiment done: {expt}')
                            job_obj.comment_append(f'{line.rstrip()}')
                            logger.info(f'Experiment done: {expt}')
                            complete_expts.append(expt)
                        else:
                            if failed_string in line:
                                expt_done = expt_done + 1
                                job_obj.comment_append('Experiment failed: '
                                                       f'{expt}')
                                job_obj.comment_append(f'{line.rstrip()}')
                                logger.info(f'Experiment failed: {expt}')
                                complete_expts.append(expt)
        # looking to see if all experiments are done
        if expt_done < len(expt_list):
            expt_done = 0
    logger.info(f'Wait Cycles completed: {72 - repeat_count}')
    job_obj.comment_append(f'Done: {len(complete_expts)} of {len(expt_list)}')
