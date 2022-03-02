#!/bin/bash --login
set -eu

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
  echo "       -h            display this help"
  echo
  return 1

}

machines=( "hera jet" )

[[ $# -lt 2 ]] && usage 
if [ "$1" = "-h" ] ; then usage ; fi

machine=$1
machine=$(echo "${machine}" | tr '[A-Z]' '[a-z]')  # need lower case machine name

py_prog=$2

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
