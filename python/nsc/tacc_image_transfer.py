import os
import numpy as np
from glob import glob
from astropy.table import Table
from dlnpyutils import utils as dln
import shutil
import time
from datetime import datetime

def make_transfer_list(n=20000):
    """
    Make a list of exposures to transfer from NOIRLab to TACC.
    """

    listdir = '/net/dl2/dnidever/nsc/instcal/v4/lists/'
    tab = Table.read(listdir+'r16avails_decam_instcal_list.fits.gz')

    print('Making TACC image transfer list')

    # Check any existing lists
    files = glob(listdir+'transfer*list_*.lst')
    files.sort()
    print('Found',len(files),'previous lists')

    # Load the previous lists
    prevlines = []
    for i in range(len(files)):
        print(files[i])
        lines = dln.readlines(files[i])
        prevlines += lines

    # Match them to FLUXFILE
    _,ind1,ind2 = np.intersect1d(prevlines,tab['FLUXFILE'],return_indices=True)
    if len(ind1)>0:
        print(len(ind1),' exposures in previous lists')
        # Delete them from the list
        del tab[ind2]
    print(len(tab),' exposures left')

    # Start the list of files
    print('Making list of',n,'exposures')
    lines = []
    for i in range(n):
        fluxfile = tab['FLUXFILE'][i]
        wtfile = tab['WTFILE'][i]
        maskfile = tab['MASKFILE'][i]
        print(i,os.path.basename(fluxfile))
        if os.path.exists(fluxfile) and os.path.exists(wtfile) and os.path.exists(maskfile):
            lines += [fluxfile,wtfile,maskfile]

    # Write the list to a file
    tstamp = datetime.now().strftime('%Y%m%d')
    outfile = 'transfer'+str(n)+'list_'+tstamp+'.lst'
    dln.writelines(listdir+outfile,lines)
    print('List written to '+listdir+outfile)
