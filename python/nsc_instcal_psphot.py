#!/usr/bin/env python

import os
import sys
import numpy as np
import warnings
from astropy.io import fits
from astropy.wcs import WCS
from astropy.table import Table
from astropy.utils.exceptions import AstropyWarning
import time
import shutil
import re
import subprocess
import glob
import logging
import socket
#from scipy.signal import convolve2d
from scipy.ndimage.filters import convolve

if __name__ == "__main__":

# Run PSPhot on one FULL DECam/Mosaic3/Bok InstCal image

    hostname = socket.gethostname()
    host = hostname.split('.')[0]

    # Version
    verdir = ""
    if len(sys.argv) > 4:
       version = sys.argv[4]
       verdir = version if version.endswith('/') else version+"/"

    # on thing/hulk use
    if (host == "thing") | (host == "hulk"):
        dir = "/dl1/users/dnidever/nsc/instcal/"+verdir
        tmproot = "/d0/dnidever/nsc/instcal/"+verdir+"tmp/"
    # on gp09 use
    if (host == "gp09") | (host == "gp08") | (host == "gp07") | (host == "gp06") | (host == "gp05"):
        dir = "/net/dl1/users/dnidever/nsc/instcal/"+verdir
        tmproot = "/data0/dnidever/nsc/instcal/"+verdir+"tmp/"

    # Make sure the directories exist
    if not os.path.exists(dir):
        os.makedirs(dir)
    if not os.path.exists(tmproot):
        os.makedirs(tmproot)


    t0 = time.time()

    print(sys.argv)

    # Not enough inputs
    n = len(sys.argv)
    if n < 4:
        print("Syntax - nsc_instcal.py fluxfile wtfile maskfile version")
        sys.exit()

    # File names
    fluxfile = sys.argv[1]
    wtfile = sys.argv[2]
    maskfile = sys.argv[3]
    # Check that the files exist
    if os.path.exists(fluxfile) == False:
        print(fluxfile, "file NOT FOUND")
        sys.exit()
    if os.path.exists(wtfile) == False:
        print(wtfile, "file NOT FOUND")
        sys.exit()
    if os.path.exists(maskfile) == False:
        print(maskile, "file NOT FOUND")
        sys.exit()

    base = os.path.basename(fluxfile)
    base = os.path.splitext(os.path.splitext(base)[0])[0]

    # 1) Prepare temporary directory
    #---------------------------------
    #print "Step #1: Preparing temporary directory"
    tmpcntr = 1
    tmpdir = tmproot+base+"."+str(tmpcntr)
    while (os.path.exists(tmpdir)):
        tmpcntr = tmpcntr+1
        tmpdir = tmproot+base+"."+str(tmpcntr)
        if tmpcntr > 20:
            print("Temporary Directory counter getting too high. Exiting")
            sys.exit()
    os.mkdir(tmpdir)
    origdir = os.getcwd()
    os.chdir(tmpdir)

    # Set up logging to screen and logfile
    #logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
    logFormatter = logging.Formatter("%(asctime)s [%(levelname)-5.5s]  %(message)s")
    rootLogger = logging.getLogger()

    logfile = tmpdir+"/"+base+".log"
    #fileHandler = logging.FileHandler("{0}/{1}.log".format(logPath, fileName))
    fileHandler = logging.FileHandler(logfile)
    fileHandler.setFormatter(logFormatter)
    rootLogger.addHandler(fileHandler)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)
    rootLogger.setLevel(logging.NOTSET)

    rootLogger.info("Running PSPhot on "+base+" on host="+host)
    rootLogger.info("  Temporary directory is: "+tmpdir)

    # 2) Copy over images from zeus1:/mss
    #-------------------------------------
    rootLogger.info("Step #2: Copying InstCal images from mass store archive")
    shutil.copyfile(fluxfile,tmpdir+"/"+os.path.basename(fluxfile))
    rootLogger.info("  "+fluxfile)
    os.symlink(os.path.basename(fluxfile),"bigflux.fits.fz")
    shutil.copyfile(wtfile,tmpdir+"/"+os.path.basename(wtfile))
    rootLogger.info("  "+wtfile)
    os.symlink(os.path.basename(wtfile),"bigwt.fits.fz")
    shutil.copyfile(maskfile,tmpdir+"/"+os.path.basename(maskfile))
    rootLogger.info("  "+maskfile)
    os.symlink(os.path.basename(maskfile),"bigmask.fits.fz")

    # Get number of extensions
    hdulist = fits.open("bigflux.fits.fz")
    nhdu = len(hdulist)
    hdulist.close()

    # 3) Run PSPhot on all subimages
    rootLogger.info("Step #3: Running PSPhot on all subimages")
    head0 = fits.getheader("bigflux.fits.fz",0)
    plver = head0.get('PLVER')
    if plver is None:
        plver = 'V1.0'
    dateobs = head0.get("DATE-OBS")
    night = dateobs[0:4]+dateobs[5:7]+dateobs[8:10]
    # instrument, c4d, k4m or ksb
    # DTINSTRU = 'mosaic3 '
    # DTTELESC = 'kp4m    '
    # Bok 90Prime data has
    if head0.get("DTINSTRU") == 'mosaic3':
      instcode = 'k4m'
      rootLogger.info("  This is KPNO Mosaic3 data")
    elif head0.get("DTINSTRU") == '90prime':
      instcode = 'ksb'
      rootLogger.info("  This is Bok 90Prime data")
    else:
      instcode = 'c4d'
      rootLogger.info("  This is CTIO DECam data")

    # Make final output directory
    if not os.path.exists(dir+instcode+"/"+night):
        os.mkdir(dir+instcode+"/"+night)
    if not os.path.exists(dir+instcode+"/"+night+"/"+base):
        os.mkdir(dir+instcode+"/"+night+"/"+base)
        rootLogger.info("  Making output directory: "+dir+instcode+"/"+night+"/"+base)

    # LOOP through the HDUs/chips
    #----------------------------
    for i in xrange(1,nhdu):
        rootLogger.info(" Processing subimage "+str(i))
        try:
            flux,fhead = fits.getdata("bigflux.fits.fz",i,header=True)
            wt,whead = fits.getdata("bigwt.fits.fz",i,header=True)
            mask,mhead = fits.getdata("bigmask.fits.fz",i,header=True)
        except:
            rootLogger.info("No extension "+str(i))

        # Use CCDNUM
        ccdnum = fhead['ccdnum']
        rootLogger.info("  CCDNUM = "+str(ccdnum))

        # FWHM values are ONLY in the extension headers
        fwhm_map = { 'c4d': 1.5 if fhead.get('FWHM') is None else fhead.get('FWHM')*0.27, 
                     'k4m': 1.5 if fhead.get('SEEING1') is None else fhead.get('SEEING1'),
                     'ksb': 1.5 if fhead.get('SEEING1') is None else fhead.get('SEEING1') }
        fwhm = fwhm_map[instcode]

        # 3a) Make subimages for flux, weight, mask
        if os.path.exists("flux.fits"):
            os.remove("flux.fits")
        fits.writeto("flux.fits",flux,header=fhead,output_verify='warn')

        # Turn the mask from integer to bitmask
        if ((instcode=='c4d') & (plver>='V3.5.0')) | (instcode=='k4m') | (instcode=='ksb'):
             #  1 = bad (in static bad pixel mask) -> 1
             #  2 = no value (for stacks)          -> 2
             #  3 = saturated                      -> 4
             #  4 = bleed mask                     -> 8
             #  5 = cosmic ray                     -> 16
             #  6 = low weight                     -> 32
             #  7 = diff detect                    -> 64
             omask = mask.copy()
             mask *= 0
             nonzero = (omask>0)
             mask[nonzero] = 2**((omask-1)[nonzero])    # This takes about 1 sec
        # Fix the DECam Pre-V3.5.0 masks
        if (instcode=='c4d') & (plver<'V3.5.0'):
          # --CP bit masks, Pre-V3.5.0 (PLVER)
          # Bit   DQ Type  PROCTYPE
          # 1  detector bad pixel          ->  1 
          # 2  saturated                   ->  4
          # 4  interpolated                ->  32
          # 16  single exposure cosmic ray ->  16
          # 64  bleed trail                ->  8
          # 128  multi-exposure transient  ->  0 TURN OFF
          # --CP bit masks, V3.5.0 on (after ~10/28/2014), integer masks
          #  1 = bad (in static bad pixel mask)
          #  2 = no value (for stacks)
          #  3 = saturated
          #  4 = bleed mask
          #  5 = cosmic ray
          #  6 = low weight
          #  7 = diff detect
          omask = mask.copy()
          mask *= 0     # re-initialize
          mask += (np.bitwise_and(omask,1)==1) * 1    # bad pixels
          mask += (np.bitwise_and(omask,2)==2) * 4    # saturated
          mask += (np.bitwise_and(omask,4)==4) * 32   # interpolated
          mask += (np.bitwise_and(omask,16)==16) * 16  # cosmic ray
          mask += (np.bitwise_and(omask,64)==64) * 8   # bleed trail

        # Use mask=1 for "bad" pixels for now
        mask[mask>0] = 1

        # Mask out bad pixels in WEIGHT image
        #  set wt=0 for mask>0 pixels
        #wt[ (mask>0) | (wt<0) ] = 0   # CP sets bad pixels to wt=0 or sometimes negative
        wt[ (mask>0) | (wt<0) ] = 1e-20   # CP sets bad pixels to wt=0 or sometimes negative

        # Create variance image
        var = 1.0 / wt
        var[ wt<1e-20 ] = 1e20

        # Change TPV to TAN, PSPhot doesn't understand TPV
        # c4d and k4m uses TPV, ksb uses TNX
        ctype1 = fhead["CTYPE1"]
        ctype2 = fhead["CTYPE2"]
        fhead["CTYPE1"] = "RA---TAN"
        fhead["CTYPE2"] = "DEC--TAN"
        whead["CTYPE1"] = "RA---TAN"
        whead["CTYPE2"] = "DEC--TAN"
        mhead["CTYPE1"] = "RA---TAN"
        mhead["CTYPE2"] = "DEC--TAN"

        #if os.path.exists("wt.fits"):
        #    os.remove("wt.fits")
        #fits.writeto("wt.fits",wt,header=whead,output_verify='warn')
        if os.path.exists("var.fits"):
            os.remove("var.fits")
        fits.writeto("var.fits",var,header=whead,output_verify='warn')

        if os.path.exists("mask.fits"):
            os.remove("mask.fits")
        fits.writeto("mask.fits",mask,header=mhead,output_verify='warn')


        # 3b) Make SExtractor config files
        # Copy the default files
        #shutil.copyfile(dir+"config/default.conv",tmpdir+"/default.conv")
        #shutil.copyfile(dir+"config/default.nnw",tmpdir+"/default.nnw")
        #shutil.copyfile(dir+"config/default.param",tmpdir+"/default.param")

        # Read in configuration file and modify for this image
        #f = open(dir+'config/default.config', 'r') # 'r' = read
        #lines = f.readlines()
        #f.close()

        # Gain, saturation, pixscale
        try:
            gainmap = { 'c4d': lambda x: 0.5*(x.get('gaina')+x.get('gainb')),
                        'k4m': lambda x: x.get('gain'),
                        'ksb': lambda x: [1.3,1.5,1.4,1.4][ccdnum-1] }  # bok gain in HDU0, use list here
            gain = gainmap[instcode](fhead)
        except:
            gainmap_avg = { 'c4d': 3.9845419, 'k4m': 1.8575, 'ksb': 1.4}
            gain = gainmap_avg[instcode]
        saturatemap = { 'c4d': fhead.get('SATURATE'),
                        'k4m': fhead.get('SATURATE'),
                        'ksb': head0.get('SATURATE') }
        saturate = saturatemap[instcode]
        pixmap = { 'c4d': 0.27, 'k4m': 0.258, 'ksb': 0.45 }
        pixscale = pixmap[instcode]

        # Things to change
        # SATUR_LEVEL     59000.00         # level (in ADUs) at which arises saturation
        # GAIN            43.52             # detector gain in e-/ADU.
        # SEEING_FWHM     1.46920            # stellar FWHM in arcsec
        # WEIGHT_IMAGE  F4-00507860_01_comb.mask.fits

        #filter_name = ''
        #cnt = 0L
        #for l in lines:
        #    # SATUR_LEVEL
        #    m = re.search('^SATUR_LEVEL',l)
        #    if m != None:
        #        lines[cnt] = "SATUR_LEVEL     "+str(saturate)+"         # level (in ADUs) at which arises saturation\n"
        #        #print "SATUR line ", cnt
        #    # Gain
        #    m = re.search('^GAIN',l)
        #    if m != None:
        #        lines[cnt] = "GAIN            "+str(gain)+"            # detector gain in e-/ADU.\n"
        #        #print "GAIN line ", cnt
        #    # SEEING_FWHM
        #    m = re.search('^SEEING_FWHM',l)
        #    if m != None:
        #        lines[cnt] = "SEEING_FWHM     "+str(fwhm)+"            # stellar FWHM in arcsec\n"
        #        #print "FWHM line ", cnt
        #    # WEIGHT_IMAGE
        #    m = re.search('^WEIGHT_IMAGE',l)
        #    if m != None:
        #        lines[cnt] = "WEIGHT_IMAGE  wt.fits    # Weight image name.\n"
        #        #print "WEIGHT line ", cnt
        #    # PHOT_APERTURES, aperture diameters in pixels
        #    m = re.search('^PHOT_APERTURES',l)
        #    if m != None:
        #        #aper_world = np.array([ 0.5, 0.75, 1.0, 1.5, 2.0, 3.5, 5.0, 7.0]) * 2  # radius->diameter
        #        aper_world = np.array([ 0.5, 1.0, 2.0, 3.0, 4.0]) * 2  # radius->diameter, 1, 2, 4, 6, 8"
        #        aper_pix = aper_world / pixscale
        #        lines[cnt] = "PHOT_APERTURES  "+', '.join(np.array(np.round(aper_pix,2),dtype='str'))+"            # MAG_APER aperture diameter(s) in pixels\n"            
        #    # Filter name
        #    m = re.search('^FILTER_NAME',l)
        #    if m != None:
        #        filter_name = (l.split())[1]
        #    cnt = cnt+1
        ## Write out the new config file
        #if os.path.exists("default.config"):
        #    os.remove("default.config")
        #fo = open('default.config', 'w')
        #fo.writelines(lines)
        #fo.close()


        # 3c) Run PSPhot
        #p = subprocess.Popen('sex', shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        rootLogger.info("  Running PSPhot")
        if os.path.exists("cat.fits"):
            os.remove("cat.fits")

        try:
            # Save the PSPhot info to a logfile
            slogfile = tmpdir+"/"+base+"_"+str(ccdnum)+".psphot.log"
            sf = open(slogfile,'w')
            retcode = subprocess.call(["psphot","-file","flux.fits","-mask","mask.fits","-variance","var.fits",base],stdout=sf,stderr=subprocess.STDOUT)
            sf.close()
            sf = open(slogfile,'r')
            slines = sf.readlines()
            sf.close()
            rootLogger.info('   '.join(slines))
            if retcode < 0:
                rootLogger.info("Child was terminated by signal"+str(-retcode))
            else:
                rootLogger.info("Child returned"+str(retcode))
        except OSError as e:
            rootLogger.info("PSPhot Execution failed:"+str(e))

        # Catch the output and put it in a logfile


        # Fix output catalog coordinates
        # origin=0 or 1???
        if os.path.exists(base+".cmf"):
            cat = Table(fits.getdata(base+".cmf",1))
            cat2 = fits.getdata(base+".cmf",2)
            fhead["CTYPE1"] = ctype1
            fhead["CTYPE2"] = ctype2
            w = WCS(fhead)
            # There's an offset of 0.5 pixels, not sure why
            r,d = w.all_pix2world(cat["X_PSF"]+0.5, cat["Y_PSF"]+0.5, 1)
            cat['RA_PSF'] = r
            cat['DEC_PSF'] = d
            os.remove(base+".cmf")
            cat.write(base+".cmf",format='fits')
            fits.append(base+".cmf",cat2)

        # 3d) Load the catalog (and logfile) and write final output file
        # Move the file to final location
        if os.path.exists(base+".cmf"):
            outcatfile = dir+instcode+"/"+night+"/"+base+"/"+base+"_"+str(ccdnum)+".cat.fits"
            outmdlfile = dir+instcode+"/"+night+"/"+base+"/"+base+"_"+str(ccdnum)+".mdl.fits"
            outpsffile = dir+instcode+"/"+night+"/"+base+"/"+base+"_"+str(ccdnum)+".psf.fits"
            # Clobber if it already exists
            if os.path.exists(outcatfile):
                os.remove(outcatfile)
                rootLogger.info("  Copying final catalog to "+outcatfile)
            # Copy to final directory
            shutil.copyfile(base+".cmf",outcatfile)
            if os.path.exists(base+".mdl.fits"):
                shutil.copyfile(base+".mdl.fits",outmdlfile)
            if os.path.exists(base+".psf"):
                shutil.copyfile(base+".psf",outpsffile)
        else:
            rootLogger.info("  No output catalog")
        # Copy log file if it finished successfully or not
        if os.path.exists(slogfile):
            outlogfile = dir+instcode+"/"+night+"/"+base+"/"+base+"_"+str(ccdnum)+".psphot.log"
            shutil.copyfile(slogfile,outlogfile)

        # 4) Delete temporary directory/files
        rootLogger.info("  Deleting subimages")
        if os.path.exists("check.fits"):
            os.remove("check.fits")
        if os.path.exists("flux.fits"):
            os.remove("flux.fits")
        if os.path.exists("wt.fits"):
            os.remove("wt.fits")
        if os.path.exists("var.fits"):
            os.remove("var.fits")
        if os.path.exists("mask.fits"):
            os.remove("mask.fits")
        if os.path.exists(base+".cmf"):
            os.remove(base+".cmf")
        if os.path.exists(base+".mdf"):
            os.remove(base+".mdf.fits")
        if os.path.exists(base+".psf"):
            os.remove(base+".psf")

    # Move the log file
    #os.rename(logfile,"/datalab/users/dnidever/decamcatalog/"+night+"/"+base+"/"+base+".log")
    # The above rename gave an error on gp09, OSError: [Errno 18] Invalid cross-device link
    shutil.move(logfile,dir+instcode+"/"+night+"/"+base+"/"+base+".log")
    #shutil.move(logfile,"/datalab/users/dnidever/decamcatalog/instcal/"+night+"/"+base+"/"+base+".log")

    # Delete temporary files and directory
    #rootLogger.info("Deleting all temporary files")
    tmpfiles = glob.glob("*")
    for f in tmpfiles:
        os.remove(f)
    os.rmdir(tmpdir)

    # CD back to original directory
    os.chdir(origdir)

    rootLogger.info(str(time.time()-t0)+" seconds")
