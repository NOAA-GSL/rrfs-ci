# Imports
import datetime
import logging
import os
import sys
from configparser import ConfigParser as config_parser

from . import rt


def run(job_obj):
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
    post_process(job_obj, build_script_loc, log_name)


def set_directories(job_obj):
    logger = logging.getLogger('BUILD/SET_DIRECTORIES')
    if job_obj.machine == 'hera':
        workdir = '/scratch2/BMC/zrtrr/rrfs_ci/autoci/pr'

    elif job_obj.machine == 'jet':
        workdir = '/lfs4/HFIP/h-nems/emc.nemspara/autort/pr'
        blstore = '/lfs4/HFIP/h-nems/emc.nemspara/RT/NEMSfv3gfs/'
        rtbldir = '/lfs4/HFIP/h-nems/emc.nemspara/RT_BASELINE/'\
                 f'emc.nemspara/FV3_RT/REGRESSION_TEST_{job_obj.compiler.upper()}'
    elif job_obj.machine == 'gaea':
        workdir = '/lustre/f2/pdata/ncep/emc.nemspara/autort/pr'
        blstore = '/lustre/f2/pdata/ncep_shared/emc.nemspara/RT/NEMSfv3gfs'
        rtbldir = '/lustre/f2/scratch/emc.nemspara/FV3_RT/'\
                 f'REGRESSION_TEST_{job_obj.compiler.upper()}'
    elif job_obj.machine == 'orion':
        workdir = '/work/noaa/nems/emc.nemspara/autort/pr'
        blstore = '/work/noaa/nems/emc.nemspara/RT/NEMSfv3gfs'
        rtbldir = '/work/noaa/stmp/bcurtis/stmp/bcurtis/FV3_RT/'\
                 f'REGRESSION_TEST_{job_obj.compiler.upper()}'
    elif job_obj.machine == 'cheyenne':
        workdir = '/glade/scratch/dtcufsrt/autort/tests/auto/pr'
        blstore = '/glade/p/ral/jntp/GMTB/ufs-weather-model/RT/NEMSfv3gfs'
        rtbldir = '/glade/scratch/dtcufsrt/FV3_RT/'\
                 f'REGRESSION_TEST_{job_obj.compiler.upper()}'
    else:
        logger.critical(f'Machine {job_obj.machine} is not supported for this job')
        raise KeyError

    logger.info(f'machine: {job_obj.machine}')
    logger.info(f'workdir: {workdir}')

    return workdir


def check_for_bl_dir(bldir, job_obj):
    logger = logging.getLogger('BUILD/CHECK_FOR_BL_DIR')
    logger.info('Checking if baseline directory exists')
    if os.path.exists(bldir):
        logger.critical(f'Baseline dir: {bldir} exists. It should not, yet.')
        job_obj.comment_text_append(f'{bldir}\n Exists already. '
                                    'It should not yet. Please delete.')
        raise FileExistsError
    return False


def create_bl_dir(bldir, job_obj):
    logger = logging.getLogger('BUILD/CREATE_BL_DIR')
    if not check_for_bl_dir(bldir, job_obj):
        os.makedirs(bldir)
        if not os.path.exists(bldir):
            logger.critical(f'Someting went wrong creating {bldir}')
            raise FileNotFoundError


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
    job_obj.comment_text_append(f'Repo location: {pr_repo_loc}')

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
            with open(file_path, 'w') as f:
                config.write(f)
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
    logger = logging.getLogger('BUILD/POST_CHECK_LOG')
    ci_log = f'{build_script_loc}/{log_name}'
    logfile_pass = process_logfile(job_obj, ci_log)
    if logfile_pass:
        move_bl_command = [[f'mv {rtbldir}/* {bldir}/', pr_repo_loc]]
        # deleted 2 lines related to orion with undefined variables
        # job_obj.run_commands(logger, move_bl_command)
        job_obj.comment_text_append('Baseline creation and move successful')
        logger.info('Starting RT Job')
        # rt.run(job_obj)
        logger.info('Finished with RT Job')
        # remove_pr_data(job_obj, pr_repo_loc, repo_dir_str, rt_dir)


def get_bl_date(job_obj, pr_repo_loc):
    logger = logging.getLogger('BUILD/UPDATE_RT_SH')
    BLDATEFOUND = False
    with open(f'{pr_repo_loc}/tests/rt.sh', 'r') as f:
        for line in f:
            if 'BL_DATE=' in line:
                logger.info('Found BL_DATE in line')
                BLDATEFOUND = True
                bldate = line
                bldate = bldate.rstrip('\n')
                bldate = bldate.replace('BL_DATE=', '')
                bldate = bldate.strip(' ')
                logger.info(f'bldate is "{bldate}"')
                logger.info(f'Type bldate: {type(bldate)}')
                bl_format = '%Y%m%d'
                try:
                    datetime.datetime.strptime(bldate, '%Y%m%d')
                except ValueError:
                    logger.info(f'Date {bldate} is not formatted YYYYMMDD')
                    raise ValueError
    if not BLDATEFOUND:
        job_obj.comment_text_append('BL_DATE not found in rt.sh.'
                                    'Please manually edit rt.sh '
                                    'with BL_DATE={bldate}')
        job_obj.job_failed(logger, 'get_bl_date()')
    logger.info('Finished get_bl_date')

    return bldate


def process_logfile(job_obj, ci_log):
    logger = logging.getLogger('BUILD/PROCESS_LOGFILE')
    fail_string = 'FAIL'
    build_failed = False
    if os.path.exists(ci_log):
        with open(ci_log) as f:
            for line in f:
                if fail_string in line:
                    build_failed = True
                    job_obj.comment_text_append(f'{line.rstrip()}')
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
