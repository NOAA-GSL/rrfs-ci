#!/bin/bash --login
set -eux

#----------------------------------------------------------------------
# This script loads the correct Python module for an HPC,
# then runs the Python program given as the second parameter.
#----------------------------------------------------------------------

function usage {
  echo
  echo "Usage: $0 machine py_prog | -h"
  echo
  echo "       machine       [required] is one of: ${machines[@]}"
  echo "       py_prog       [required] Python program to run"
  echo "       test_list     [optional] List of tests for ci_auto.py"
  echo "                     default is auto_expts_list.txt - 2 tests"
  echo "       -h            display this help"
  echo
  return 1

}

machines=( "hera jet" )

[[ $# -lt 2 ]] && usage 
if [ "$1" = "-h" ] ; then usage ; fi

export machine=$1
machine=$(echo "${machine}" | tr '[A-Z]' '[a-z]')  # need lower case machine name

export py_prog=$2

if [[ $# -lt 3 ]] ; then
   export test_list="auto_expts_list.txt"
else
   export test_list=$3
fi

if [[ ${py_prog} == "ci_auto.py" ]] ; then
   if [ ! -f ${test_list} ]; then
     echo "Test list file ${test_list} does not exist."
     exit 1
   fi
   export py_prog="${py_prog} ${test_list}"
fi

if [[ ${machine} == hera ]]; then
  module use -a /contrib/miniconda3/modulefiles
  module load miniconda3
  conda activate github_auto
elif [[  ${machine} == jet ]]; then
  # left in this format in case hera and jet diverge
  module use -a /contrib/miniconda3/modulefiles
  module load miniconda3
  conda activate github_auto
else
  echo "No Python Path for machine ${machine}."
  exit 1
fi

python ${py_prog}

exit 0
