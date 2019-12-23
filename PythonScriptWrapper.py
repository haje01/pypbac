#
# This is mock up of PythonScriptWrapper.py file, which would be genrated by Power BI.
# Run connector script with this file for testing. Example:
#   $ python connector.py PythonScriptWrapper.py
#
import os, pandas, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot

os.chdir(u'E:/works/pypbac/temp')
matplotlib.pyplot.show = lambda args=None,kw=None: ()
# Original Script. Please update your script content here and once completed copy below section back to the original editing window #
[filter]
1: country = 'kr'

# Epilog - Auto Generated #
os.chdir(u'E:/works/pypbac/temp')
for key in dir():
    if (type(globals()[key]) is pandas.DataFrame):
        (globals()[key]).to_csv(key + '.csv', index = False)