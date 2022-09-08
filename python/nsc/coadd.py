#!/usr/bin/env python
#
# COADD.PY   This is used to create coadds.
#

__authors__ = 'David Nidever <dnidever@montana.edu>'
__version__ = '20170911'  # yyyymmdd


"""
    Software to create an NSC coadd.

"""


import os
import sys
import numpy as np
import shutil
#import scipy
import warnings
from astropy.io import fits
from astropy.utils.exceptions import AstropyWarning
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
from scipy.interpolate import RectBivariateSpline
#from skimage import measure, morphology
#from scipy.signal import argrelmin
#import scipy.ndimage.filters as filters
import time
import glob
import logging
import sep
import healpy as hp
from reproject import reproject_interp
import tempfile
import subprocess
import glob
from dlnpyutils import utils as dln, coords

    
def brickwcs(ra,dec,npix=3600,step=0.262):
    """ Create the WCS and header for a brick."""

    # This creates a brick WCS given the brick structure

    # Make the tiling file
    #---------------------
    # Lines with the tiling scheme first
    nx = npix
    ny = npix
    step = step / npix
    xref = nx//2
    yref = ny//2

    w = WCS()
    w.wcs.crpix = [xref+1,yref+1]
    w.wcs.cdelt = np.array([step,step])
    w.wcs.crval = [ra,dec]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.array_shape = (npix,npix)

    #  Make the header as well
    hdu = fits.PrimaryHDU()
    head = hdu.header

    head['NAXIS'] = 2
    head['NAXIS1'] = nx
    head['CDELT1'] = step
    head['CRPIX1'] = xref+1
    head['CRVAL1'] = ra
    head['CTYPE1'] = 'RA---TAN'
    head['NAXIS2'] = ny
    head['CDELT2'] = step
    head['CRPIX2'] = yref+1
    head['CRVAL2'] = dec
    head['CTYPE2'] = 'DEC--TAN'
    #head['BRAMIN'] = brickstr.ra1,'RA min of unique brick area'
    #head['BRAMAX'] = brickstr.ra2,'RA max of unique brick area'
    #head['BDECMIN'] = brickstr.dec1,'DEC min of unique brick area'
    #head['BDECMAX'] = brickstr.dec2,'DEC max of unique brick area'

    return w,head

def inNativeByteOrder(im):
    """ Put image in native byte order."""
    if ((im.dtype.byteorder=='<') & (sys.byteorder=='big')) | ((im.dtype.byteorder=='>') & (sys.byteorder=='little')):
        return im.byteswap(inplace=True).newbyteorder()
    else:
        return im

def doImagesOverlap(head1,head2):
    """ Do the two images overlap."""

    if isinstance(head1,WCS):
        wcs1 = head1
    else:
        wcs1 = WCS(head1)
    ny1,nx1 = wcs1.array_shape
    ra1,dec1 = wcs1.wcs_pix2world(nx1/2,ny1/2,0)
    vra1,vdec1 = wcs1.wcs_pix2world([0,nx1-1,nx1-1,0],[0,0,ny1-1,ny1-1],0)
    vlon1,vlat1 = coords.rotsphcen(vra1,vdec1,ra1,dec1,gnomic=True)

    if isinstance(head2,WCS):
        wcs2 = head2
    else:
        wcs2 = WCS(head2)
    ny2,nx2 = wcs2.array_shape
    vra2,vdec2 = wcs2.wcs_pix2world([0,nx2-1,nx2-1,0],[0,0,ny2-1,ny2-1],0)
    vlon2,vlat2 = coords.rotsphcen(vra2,vdec2,ra1,dec1,gnomic=True)

    olap = coords.doPolygonsOverlap(vlon1,vlat1,vlon2,vlat2)

    return olap

 
def adxyinterp(head,rr,dd,nstep=10,xyad=False):
    """
    Instead of transforming the entire large 2D RA/DEC 
    arrays to X/Y do a sparse grid and perform linear 
    interpolation to the full size. 
 
    Parameters
    ----------
    head : header
       The FITS header with the WCS. 
    rr : numpy array
       The 2D RA array. 
    dd  : numpy array
       The 2D DEC array. 
    nstep : int, optional
       The undersampling to use, default nstep=10. 
    xyad : bool, optional
       Perform X/Y->RA/DEC conversion instead. 
          In this case the meaning of the coordinate 
          arrays are flipped, i.e. rr/dd<->xx/yy 
 
    Returns
    -------
    xx : numpy array
       The 2D X array. 
    yy : numpy array
       The 2D Y array. 
 
    Example
    -------

    xx,yy = adxyinterp(head,ra,dec,nstep=10)
            
    By D. Nidever  Oct. 2016 
    Translated to Python by D. Nidever, April 2022
    """

    nx,ny = rr.shape
    nxs = (nx-1)//nstep + 1 
    nys = (ny-1)//nstep + 1 

    wcs = WCS(head)
     
    # Small dimensions, just transform the full grid 
    if nx <= nstep or ny <= nstep: 
        if xyad==False:
            xx,yy = wcs.world_to_pixel(SkyCoord(ra=rr,dec=dd,unit='deg'))
        else:
            coo = wcs.pixel_to_world(rr,dd)
            xx = coo.ra.deg
            yy = coo.dec.deg

    # Subsample the RA/DEC arrays 
    rrs = rr[0:nx:nstep,0:ny:nstep] 
    dds = dd[0:nx:nstep,0:ny:nstep] 
    if xyad==False:
        xxs,yys = wcs.world_to_pixel(SkyCoord(ra=rrs,dec=dds,unit='deg'))
    else:
        coos = wcs.pixel_to_world(rrs,dds)
        xxs = coos.ra.deg
        yys = coos.dec.deg
     
    # Start final arrays 
    xx = np.zeros((nx,ny),float)
    yy = np.zeros((nx,ny),float)
     
    # Use CONGRID to perform the linear interpolation 
    #   congrid normally does nx_out/nx_in scaling 
    #   if /minus_one set it does (nx_out-1)/(nx_in-1) 

    xx0,yy0 = np.arange(xxs.shape[0]),np.arange(xxs.shape[1])
    xx1 = np.arange((nxs-1)*nstep+1)/((nxs-1)*nstep)*(xxs.shape[0]-1)
    yy1 = np.arange((nys-1)*nstep+1)/((nys-1)*nstep)*(xxs.shape[1]-1)
    ixx = RectBivariateSpline(xx0,yy0,xxs,kx=1,ky=1)(xx1,yy1)
    iyy = RectBivariateSpline(xx0,yy0,yys,kx=1,ky=1)(xx1,yy1)
    xx[0:(nxs-1)*nstep+1,0:(nys-1)*nstep+1] = ixx 
    yy[0:(nxs-1)*nstep+1,0:(nys-1)*nstep+1] = iyy 
     
    # Deal with right edge 
    if (nxs-1)*nstep+1 < nx: 
        # Make a short grid in X at the right edge 
        rrs_rt = rr[nx-nstep-1:nx:nstep,0:ny:nstep] 
        dds_rt = dd[nx-nstep-1:nx:nstep,0:ny:nstep] 
        if xyad==False:
            xxs_rt,yys_rt = wcs.world_to_pixel(SkyCoord(ra=rrs_rt,dec=dds_rt,unit='deg'))
        else: 
            coo_rt = wcs.pixel_to_world(rrs_rt,dds_rt)
            xxs_rt = coo_rt.ra.deg
            yys_rt = coo_rt.dec.deg

        xx0_rt,yy0_rt = np.arange(xxs_rt.shape[0]),np.arange(xxs_rt.shape[1])
        xx1_rt = np.arange(nstep+1)/nstep*(xxs_rt.shape[0]-1)
        yy1_rt = np.arange((nys-1)*nstep+1)/((nys-1)*nstep)*(xxs_rt.shape[1]-1)
        ixx_rt = RectBivariateSpline(xx0_rt,yy0_rt,xxs_rt,kx=1,ky=1)(xx1_rt,yy1_rt)
        iyy_rt = RectBivariateSpline(xx0_rt,yy0_rt,yys_rt,kx=1,ky=1)(xx1_rt,yy1_rt)
        xx[nx-nstep-1:nx,0:(nys-1)*nstep+1] = ixx_rt
        yy[nx-nstep-1:nx,0:(nys-1)*nstep+1] = iyy_rt 

    # Deal with top edge 
    if (nys-1)*nstep+1 < ny: 
        # Make a short grid in Y at the top edge 
        rrs_tp = rr[0:nx:nstep,ny-nstep-1:ny:nstep] 
        dds_tp = dd[0:nx:nstep,ny-nstep-1:ny:nstep] 
        if xyad==False:
            xxs_tp, yys_tp = wcs.world_to_pixel(SkyCoord(ra=rrs_tp,dec=dds_tp,unit='deg'))
        else: 
            coo_tp = wcs.pixel_to_world(rrs_tp,dds_tp)
            xxs_tp = coo_tp.ra.deg
            yys_tp = coo_tp.dec.deg

        xx0_tp,yy0_tp = np.arange(xxs_tp.shape[0]),np.arange(xxs_tp.shape[1])
        xx1_tp = np.arange((nxs-1)*nstep+1)/((nxs-1)*nstep)*(xxs_tp.shape[0]-1)
        yy1_tp = np.arange(nstep+1)/nstep*(xxs_tp.shape[1]-1)
        ixx_tp = RectBivariateSpline(xx0_tp,yy0_tp,xxs_tp,kx=1,ky=1)(xx1_tp,yy1_tp)
        iyy_tp = RectBivariateSpline(xx0_tp,yy0_tp,yys_tp,kx=1,ky=1)(xx1_tp,yy1_tp)
        xx[0:(nxs-1)*nstep+1,ny-nstep-1:ny] = ixx_tp 
        yy[0:(nxs-1)*nstep+1,ny-nstep-1:ny] = iyy_tp 

    # Deal with top/right corner 
    if (nxs-1)*nstep+1 < nx and (nys-1)*nstep+1 < ny: 
        # Make a short grid in X and Y at the top-right corner 
        rrs_tr = rr[nx-nstep-1:nx:nstep,ny-nstep-1:ny:nstep] 
        dds_tr = dd[nx-nstep-1:nx:nstep,ny-nstep-1:ny:nstep] 
        if xyad==False:
            xxs_tr, yys_tr = wcs.world_to_pixel(SkyCoord(ra=rrs_tr,dec=dds_tr,unit='deg'))
        else: 
            coo_tr = wcs.pixel_to_world(rrs_tr,dds_tr)
            xxs_tr = coo_tr.ra.deg
            yys_tr = coo_tr.dec.deg

        xx0_tr,yy0_tr = np.arange(xxs_tr.shape[0]),np.arange(xxs_tr.shape[1])
        xx1_tr = np.arange(nstep+1)/nstep*(xxs_tr.shape[0]-1)
        yy1_tr = np.arange(nstep+1)/nstep*(xxs_tr.shape[1]-1)
        ixx_tr = RectBivariateSpline(xx0_tr,yy0_tr,xxs_tr,kx=1,ky=1)(yy1_tr,xx1_tr)
        iyy_tr = RectBivariateSpline(xx0_tr,yy0_tr,yys_tr,kx=1,ky=1)(yy1_tr,xx1_tr)
        xx[nx-nstep-1:nx,ny-nstep-1:ny] = ixx_tr
        yy[nx-nstep-1:nx,ny-nstep-1:ny] = iyy_tr

    return xx,yy

def image_reproject_bilinear(im,head,outhead,wtim=None,verbose=False):
    """
    Resample image using python bilinear RectBivariateSpline.

    Parameters
    ----------
    im : numpy array
       Input image.
    head : Header
       Header for the input image that containts the WCS.
    outhead : Header
       Header for the output image that contains the WCS.
    wtim : numpy array, optional
       Weight image.
    verbose : boolean, optional
       Verbose output to the screen.

    Returns
    -------
    oim : numpy array
       Resampled image.
    ohead : Header
       Header for resampled image.
    owtim : numpy array
       Resampled weight image.  Only if wtim is input.

    Example
    -------

    out = image_reproject_bilinear(im,head,outhead)

    """

    t0 = time.time()

    if isinstance(head,WCS):
        wcs = head
    else:
        wcs = WCS(head)
    if isinstance(outhead,WCS):
        outwcs = outhead
    else:
        outwcs = WCS(outhead)

    ny,nx = im.shape
    fnx,fny = outwcs.array_shape

    # Make the wtim if not input
    #   1-good, 0-bad
    if wtim is None:   
        wtim = np.ones(ny,nx,float)
        saturate = head.get('saturate')
        if satuate is not None:
            gdpix = (im < saturate)
            bdpix = (im >= saturate)
            if np.sum(bdpix) > 0:
                background = np.nanmedian(im[gdpix])
                wtim[bdpix] = 0.0
                im[bdpix] = background

    # Get image ra/dec vertices
    vcoo = wcs.pixel_to_world([0,nx-1,nx-1,0],[0,0,ny-1,ny-1])
    vertices_ra = vcoo.ra.deg
    vertices_dec = vcoo.dec.deg

    # 2D RA/DEC arrays for final image
    xb = np.zeros(fny,float).reshape(-1,1) + np.arange(fnx).reshape(1,-1)
    yb = np.arange(fny).reshape(-1,1) + np.zeros(fnx).reshape(1,-1)
    bcoo = outwcs.pixel_to_world(xb,yb)
    rab = bcoo.ra.deg
    decb = bcoo.dec.deg

    # Get X/Y range for this image in the final coordinate system
    vx,vy = outwcs.world_to_pixel(SkyCoord(ra=vertices_ra,dec=vertices_dec,unit='deg'))
    xout = [np.maximum(np.floor(np.min(vx))-2, 0),
            np.minimum(np.ceil(np.max(vx))+2, fnx-2)+1]
    xout = np.array(xout).astype(int)
    nxout = int(xout[1]-xout[0])
    yout = [np.maximum(np.floor(np.min(vy))-2, 0),
            np.minimum(np.ceil(np.max(vy))+2, fny-2)+1]
    yout = np.array(yout).astype(int)
    nyout = int(yout[1]-yout[0])
    rr = rab[yout[0]:yout[1],xout[0]:xout[1]]
    dd = decb[yout[0]:yout[1],xout[0]:xout[1]]
    xx,yy = adxyinterp(head,rr,dd,nstep=10)

    # The x/y position to bilinear need to be in the original system, ~1sec
    rim = np.zeros(xx.shape,float)
    rwtim = np.zeros(xx.shape,bool)
    good = ((xx>=0) & (xx<=im.shape[1]-1) & (yy>=0) & (yy<=im.shape[0]-1))
    if np.sum(good)>0:
        rim[good] = RectBivariateSpline(np.arange(im.shape[0]),np.arange(im.shape[1]),im,kx=1,ky=1).ev(yy[good],xx[good])
        rwtim[good] = RectBivariateSpline(np.arange(im.shape[0]),np.arange(im.shape[1]),wtim,kx=1,ky=1).ev(yy[good],xx[good])
 
    # Contruct final image
    oim = np.zeros((fny,fnx),float)
    oim[yout[0]:yout[1],xout[0]:xout[1]] = rim
    owtim = np.zeros((fny,fnx),bool)
    owtim[yout[0]:yout[1],xout[0]:xout[1]] = rwtim
 

    # Contruct the final header
    ohead = head.copy()
    # Delete any previous WCS keywords
    for n in ['CRVAL1','CRVAL2','CRPIX1','CRPIX2','CDELT1','CDELT2','CTYPE1','CTYPE2','CD1_1','CD1_2','CD2_1','CD2_2']:
        if n in ohead:
            del ohead[n]
    cards = [f[0] for f in ohead.cards]
    pvnames = dln.grep(cards,'PV[0-9]_+[0-9]')
    for p in pvnames:
        del ohead[p]
    # Add the new WCS
    whead = outwcs.to_header()
    ohead.extend(whead)
    ohead['NAXIS1'] = fnx
    ohead['NAXIS2'] = fny

    dt = time.time()-t0
    if verbose:
        print('dt = %8.2f sec' % dt)

    return oim,ohead,owtim
        

def image_reproject_swarp(im,head,outhead,wtim=None,tmproot='.',verbose=False):
    """
    Reproject image onto new projection with interpolation with Swarp.

    Parameters
    ----------
    im : numpy array
       Input image.
    head : Header
       Header for the input image that containts the WCS.
    outhead : Header
       Header for the output image that contains the WCS.
    wtim : numpy array, optional
       Weight image.
    tmproot : str
       Temporary directory to use for the work.  Default is the current directory.
    verbose : boolean, optional
       Verbose output to the screen.

    Returns
    -------
    oim : numpy array
       Resampled image.
    ohead : Header
       Header for resampled image.
    owtim : numpy array
       Resampled weight image.  Only if wtim is input.

    Example
    -------

    out = image_reproject_swarp(im,head,outhead)

    """

    t0 = time.time()

    if isinstance(head,WCS):
        wcs = head
    else:
        wcs = WCS(head)
    if isinstance(outhead,WCS):
        outwcs = outhead
    else:
        outwcs = WCS(outhead)

    # Make temporary directory and CD to it
    tmpdir = os.path.abspath(tempfile.mkdtemp(prefix="swrp",dir=tmproot))
    origdir = os.path.abspath(os.curdir)
    os.chdir(tmpdir)

    # Write image to temporary file
    imfile = 'image.fits'
    fits.PrimaryHDU(im,head).writeto(imfile,overwrite=True)
    if wtim is not None:
        wtfile = 'wt.fits'
        fits.PrimaryHDU(wtim,head).writeto(wtfile,overwrite=True)

    # Use swarp to do the resampling

    # Create configuration file
    # fields to modify: IMAGEOUT_NAME, WEIGHTOUT_NAME, WEIGHT_IMAGE, CENTER, PIXEL_SCALE, IMAGE_SIZE, GAIN?
    fil = os.path.abspath(__file__)
    codedir = os.path.dirname(os.path.dirname(os.path.dirname(fil)))
    paramdir = codedir+'/params/'
    shutil.copyfile(paramdir+"swarp.config",tmpdir+"/swarp.config")
    configfile = "swarp.config"
    clines = dln.readlines(configfile)

    imoutfile = 'image.out.fits'
    if wtim is not None:
        wtoutfile = 'wt.out.fits'

    # IMAGEOUT_NAME
    ind = dln.grep(clines,'^IMAGEOUT_NAME ',index=True)[0]
    clines[ind] = 'IMAGEOUT_NAME        '+imoutfile+'     # Output filename'
    # Weight parameteres
    if wtim is not None:
        # WEIGHTOUT_NAME
        ind = dln.grep(clines,'^WEIGHTOUT_NAME ',index=True)[0]
        clines[ind] = 'WEIGHTOUT_NAME    '+wtoutfile+' # Output weight-map filename'
        # WEIGHT_TYPE
        ind = dln.grep(clines,'^WEIGHT_TYPE ',index=True)[0]
        clines[ind] = 'WEIGHT_TYPE         MAP_WEIGHT            # BACKGROUND,MAP_RMS,MAP_VARIANCE'
        # WEIGHT_IMAGE
        ind = dln.grep(clines,'^WEIGHT_IMAGE ',index=True)[0]
        clines[ind] = 'WEIGHT_IMAGE      '+wtfile+'    # Weightmap filename if suffix not used'
    else:
        # Remove WEIGHT keywords
        ind = dln.grep(clines,'^WEIGHT_TYPE ',index=True)[0]
        clines[ind] = 'WEIGHT_TYPE            NONE            # BACKGROUND,MAP_RMS,MAP_VARIANCE'
        #ind = dln.grep(clines,'^WEIGHT',index=True)
        #clines = dln.remove_indices(clines,ind)
    # CENTER
    ind = dln.grep(clines,'^CENTER ',index=True)[0]
    clines[ind] = 'CENTER         %9.6f, %9.6f  # Coordinates of the image center' % (outwcs.wcs.crval[0],outwcs.wcs.crval[1])
    # PIXEL_SCALE
    onx,ony = outwcs.array_shape
    r,d = outwcs.all_pix2world([onx//2,onx//2],[ony//2,ony//2+1],0)
    pixscale = (d[1]-d[0])*3600
    ind = dln.grep(clines,'^PIXEL_SCALE ',index=True)[0]
    clines[ind] = 'PIXEL_SCALE           %6.3f             # Pixel scale' % pixscale
    # IMAGE_SIZE
    ind = dln.grep(clines,'^IMAGE_SIZE ',index=True)[0]
    clines[ind] = 'IMAGE_SIZE             %d,%d               # Image size (0 = AUTOMATIC)' % outwcs.array_shape
    # GAIN??
    #ind = dln.grep(clines,'^GAIN_KEYWORD ',index=True)[0]
    #clines[ind] = 'GAIN_KEYWORD           GAIN            # FITS keyword for effect. gain (e-/ADU)'

    # Write the updated configuration file
    dln.writelines(configfile,clines,overwrite=True)

    # Run swarp
    if verbose is False:
        #slogfile = "swarp.log"
        #sf = open(slogfile,'w')
        #retcode = subprocess.call(["swarp",imfile,"-c",configfile],stdout=sf,stderr=subprocess.STDOUT,shell=False)
        #sf.close()
        #slines = dln.readlines(slogfile)
        retcode = subprocess.check_output(["swarp",imfile,"-c",configfile],shell=False,stderr=subprocess.STDOUT)        
    else:
        retcode = subprocess.run(["swarp",imfile,"-c",configfile],shell=False,stderr=subprocess.STDOUT)        
                
    # Load the output file
    oim,ohead = fits.getdata(imoutfile,header=True)
    # By default swarp makes it sky-right, flip
    if ohead['CD1_1'] < 0:
        if verbose:
            print('Flipping swarp image in RA axis')
        oim = oim[:,::-1]
        ohead['CD1_1'] = -ohead['CD1_1']
    out = (oim,ohead)
    if wtim is not None:
        owtim,owthead = fits.getdata(wtoutfile,header=True)
        out = (oim,ohead,owtim)

    # Delete temporary directory and files??
    tmpfiles = glob.glob('*')
    for f in tmpfiles:
        os.remove(f)
    os.rmdir(tmpdir)

    # Go back to the original direcotry
    os.chdir(origdir)

    dt = time.time()-t0
    if verbose:
        print('dt = %8.2f sec' % dt)

    return out

    #ny1,nx1 = im.shape
    ## The coordinates vary smoothly, only get coordinate in new system for a sparse matrix
    ##  using the wcs to go from pix->world->pix takes 15 sec for 2046x4098 image
    ##  this way takes 4 sec
    #x1, y1 = np.mgrid[0:nx1+100:100,0:ny1+100:100]
    #ra,dec = wcs.all_pix2world(x1,y1,0)
    #x2,y2 = outwcs.wcs_world2pix(ra,dec,0)
    ## Now interpolate this for all pixels
    #from scipy import interpolate
    #xfn = interpolate.interp2d(x1.flatten(),y1.flatten(),x2.flatten(),kind='cubic',bounds_error=True,copy=False)
    #yfn = interpolate.interp2d(x1.flatten(),y1.flatten(),y2.flatten(),kind='cubic',bounds_error=True,copy=False)
    ##x1all,y1all = np.mgrid[0:nx1,0:ny1]  # slow
    #x1all = np.arange(nx1).repeat(ny1).reshape(nx1,ny1).T
    #y1all = np.arange(ny1).repeat(nx1).reshape(ny1,nx1)
    #x2all = xfn(np.arange(nx1),np.arange(ny1))
    #y2all = yfn(np.arange(nx1),np.arange(ny1))
    ## Interpolate the image
    #from scipy import ndimage

    #import pdb; pdb.set_trace()
    ## coords = [1d x array, 1d y array]
    ##  coords in 2D image IM where we want interpolated values
    ## so we actually want to go the OTHER for this, what are the final x/y values in the ORIGINAL image
    #newim = ndimage.map_coordinates(im,[[0.5,2],[0.5,1]],order=1)
    #newim = ndimage.map_coordinates(im, coords, order=1, cval=0, output=bool)
    #imfx = interpolate.interp2d(x2all.flatten(),y2all.flatten(),im.flatten(),kind='cubic',bounds_error=True,copy=False)
    #tck = interpolate.bisplrep(x2all.flatten(),y2all.flatten(),im.flatten())
    
    #znew = interpolate.bisplev(xnew[:,0], ynew[0,:], tck)

def image_reproject(im,head,outhead,wtim=None,kind='swarp',tmproot='.',verbose=False):
    """
    Reproject image onto new projection with interpolation.
    Wrapper for the _swarp and _bilinear functions
    """

    if kind == 'swarp':
        return image_reproject_swarp(im,head,outhead,wtim=wtim,tmproot=tmproot,verbose=verbose)
    elif kind == 'bilinear':
        return image_reproject_swarp(im,head,outhead,wtim=wtim,verbose=verbose)
    else:
        raise ValueError(kind,' not supported')
    

def image_interp(imagefile,outhead,weightfile=None,masknan=False):
    """ Interpolate a single image (can be multi-extension) to the output WCS."""

    if os.path.exists(imagefile) is False:
        raise ValueError(imagefile+" NOT FOUND")
    if weightfile is not None:
        if os.path.exists(weightfile) is False:
            raise ValueError(weightfile+" NOT FOUND")    

    # Output vertices
    bricknx = outhead['NAXIS1']
    brickny = outhead['NAXIS1']
    brickwcs = WCS(outhead)
    brickra,brickdec = brickwcs.wcs_pix2world(bricknx/2,brickny/2,0)
    brickvra,brickvdec = brickwcs.wcs_pix2world([0,bricknx-1,bricknx-1,0],[0,0,brickny-1,brickny-1],0)
    brickvlon,brickvlat = coords.rotsphcen(brickvra,brickvdec,brickra,brickdec,gnomic=True)

    # How many extensions
    hdulist = fits.open(imagefile)
    nimhdu = len(hdulist)
    hdulist.close()
    if weightfile is not None:
        hdulist = fits.open(weightfile)
        nwthdu = len(hdulist)
        hdulist.close()    
        if nimhdu != nwthdu:
            raise ValueError(imagefile+' and '+weightfile+' do NOT have the same number of extensions.')

    # Open the files
    imhdulist = fits.open(imagefile)
    if weightfile is not None:
        wthdulist = fits.open(weightfile)

    # Initialize final images
    fnx = outhead['NAXIS1']
    fny = outhead['NAXIS2']    
    fim = np.zeros((fnx,fny),float)
    fwt = np.zeros((fnx,fny),float)
    fbg = np.zeros((fnx,fny),float)
        
    # Loop over the HDUs
    for i in range(nimhdu):           
        # Just get the header
        head = imhdulist[i].header
        if head['NAXIS']==0:    # no image
            continue
        wcs = WCS(head)
        nx1 = head['NAXIS1']
        ny1 = head['NAXIS2']

        # Check that it overlaps the final area
        if doImagesOverlap(brickwcs,wcs) is False:
            continue
            
        mask = None
        # Flux image
        im = imhdulist[i].data
        head = imhdulist[i].header
        im = inNativeByteOrder(im)      # for sep need native byte order  
        nx1,ny1 = im.shape
        # Weight image
        if weightfile is not None:
            wt = wthdulist[i].data
            whead = wthdulist[i].header
            wt = inNativeByteOrder(wt)
            mask = (wt<=0)

        # Mask NaNs/Infs
        if masknan is True:
            if mask is not None:
                mask = (mask==True) | ~np.isfinite(im)
            else:
                mask = ~np.isfinite(im)
            im[mask] = np.median(im[~mask])


        # Step 1. Background subtract the image
        bkg = sep.Background(im, mask=mask, bw=64, bh=64, fw=3, fh=3)
        bkg_image = bkg.back()
        im -= bkg_image
        im[mask] = 0
        
        import pdb; pdb.set_trace()

        newim = image_reproject(im,head,outhead)



        # Step 2. Reproject the image
        newim, footprint = reproject_interp((im,head), outhead)
        if weightfile is not None:
            newwt, wfootprint = reproject_interp((wt,whead), outhead)
        newbg, bfootprint = reproject_interp((bkg_image,head), outhead)        

        # Step 3. Add to final images
        fim += newim
        if weightfile is not None:
            fwt += newwt
        fbg += newbg

    return fim,fwt,fbf

    
def meancube(imcube,wtcube,weights=None,crreject=False):
    """ This does the actual stack of an image cube.  The images must already be background-subtracted and scaled."""
    # Weights should be normalized, e.g., sum(weights)=1
    # pixels to be masked in an image should have wtcube = 0

    nx,ny,nimages = imcube.shape

    # Unweighted
    if weights is None:
        weights = np.ones(nimages,float)/nimages
    
    # Do the weighted average
    finaltot = np.zeros((nx,ny),float)
    finaltotwt = np.zeros((nx,ny),float)        
    totvarim = np.zeros((nx,ny),float)
    for i in range(nimages):
        mask = (wtcube[:,:,i] > 0)
        var = np.zeros((nx,ny),float)  # sig^2
        var[mask] = 1/wtcube[:,:,mask]
        finaltot[mask] += imcube[:,:,mask]*weights[i]
        finaltotwt[mask] += weights[i]
        # Variance in each pixel for noise images and the scalar weights
        totvarim[mask] += weights[i]*var
    # Create the weighted average image
    finaltotwt[finaltotwt<=0] = 1
    final = finaltot/finaltotwt
    # Create final error image
    error = np.sqrt(finalvarim)
    
    # CR rejection
    if crreject is True:
        pass
    
    return final,error


def stack(imagefiles,errorfiles,bgfiles,weights=None):
    """ Actually do the stacking/averaging of multiple images already reprojected."""

    # DO NOT use the error maps for the weighted average.  Use scalar weights for each exposure.
    #  otherwise you'll get screwy images
    # Only use the error maps to generate the final error image
    
    # imagefiles/weightfiles, list of filenames

    # The images should already be background subtracted and scaled
    
    # How many subimages
    file1 = imagefiles[0]
    hdu = fits.open(file1)
    nbin = len(hdu)
    hdu.close()

    # Original image size
    head = fits.getheader(imagegfiles[0],0)
    fnx = head['ONAXIS1']
    fny = head['ONAXIS2']
    
    # Get the sizes and positions of the subimages
    dtype = np.dtype([('SUBX0',int),('SUBX1',int),('SUBY0',int),('SUBY1',int),('NX',int),('NY',int)])
    binstr = np.zeros(nbin,dtype=dtype)
    for b in range(nbin):
        head = fits.getheader(imagefiles[0],b)
        substr['X0'][b] = head['SUBX0']
        substr['X1'][b] = head['SUBX1']
        substr['Y0'][b] = head['SUBY0']
        substr['Y1'][b] = head['SUBY1']        
        binstr['NX'][b] = head['SUBNX']
        binstr['NY'][b] = head['SUBNY']

    # Final image
    final = np.zeros((fnx,fny),float)
    error = np.zeros((fnx,fny),float)    
        
    # Loop over bins
    for b in range(nbin):
        imcube = np.zeros((substr['NX'][b],substr['NY'][b],nimages),np.float64)
        wtcube = np.zeros((substr['NX'][b],substr['NY'][b],nimages),np.float64)        
        # Loop over images
        for f in range(nimages):
            im,head = fits.getheader(imagefiles[f],b,header=True)
            wt,whead = fits.getheader(weightfiles[f],b,header=True)
            # Background subtraction here???
            # Deal with NaNs
            wt[~np.isfinite(im)] = 0
            # Stuff into the cube
            imcube[:,:,f] = im
            wtcube[:,:,f] = wt
        # Do the weighted combination
        avgim,errim = meancube(imcube,wtcube,weights=weights)
        # Stuff into final image
        final[substr['X0'][b]:substr['X1'][b]+1,substr['Y0'][b]:substr['Y1'][b]+1] = avgim
        error[substr['X0'][b]:substr['X1'][b]+1,substr['Y0'][b]:substr['Y1'][b]+1] = errim

    return final,error

    
def coadd(imagefiles,weightfiles,meta,outhead,coaddtype='average'):
    """ Create a coadd given a list of images. """

    # meta should have zpterm, exptime, fwhm
    
    nimages = dln.size(imagefiles)

    # PUT ALL CHIPS FROM THE SAME EXPOSURE INTO THE SAME REBINNED IMAGE!!!
    # if they fiels are MEF, then interp them all!!
    # make an interp_single() function interpim, resampim
    
    # Figure out scales and weights
    # F_trans = 10^(-0.8*(delta_mag-0.2))    
    scales = meta['exptime'] * 10**(-0.8*(meta['zpterm']-0.2))

    # Use weight~S/N
    # S/N goes as sqrt(exptime) and in background-dominated regime S/N ~ 1/FWHM
    # so maybe something like weight ~ sqrt(scaling)/FWHM
    weights = np.sqrt(scales)/meta['fwhm']
    weights /= np.sum(weights)    # normalize

    # Loop over the images
    tempfiles = []
    tempwtfiles = []
    tempbgfiles = []
    for f in range(nimages):

        # Interpolate image
        fim, fwt, fbg = image_interp(imagefiles[f],outhead,weightfile=weightfiles[f])

        # Flux image
        imfile = imagefiles[f]        
        # Check for extension at the end, e.g., image.fits[3]
        if imfile.endswith(']') & (imfile.find('[')>-1):
            lo = imfile.find('[')
            exten = imfile[lo:-2]
            imfile = imfile[0:lo]
        else:
            exten = 0
        im,head = fits.getheader(imagefiles[f],exten,header=True)
        im = im.byteswap(inplace=True).newbyteorder()    # for sep need native byte order
        # Weight image
        wtfile = wtfiles[f]        
        # Check for extension at the end, e.g., image.fits[3]
        if wtfile.endswith(']') & (wtfile.find('[')>-1):
            lo = wtfile.find('[')
            exten = wtfile[lo:-2]
            wtfile = wtfile[0:lo]
        else:
            exten = 0
        wt,whead = fits.getheader(weightfiles[f],exten,header=True)
        wt = wt.byteswap(inplace=True).newbyteorder()
        nx1,ny1 = im.shape
        
        # Step 1. Background subtract the image
        bkg = sep.Background(data, mask=mask, bw=64, bh=64, fw=3, fh=3)
        bkg_image = bkg.back()
        im -= bkg_image
        
        # Step 2. Reproject the image
        newim, footprint = reproject_interp((im,head), outhead)
        newwt, wfootprint = reproject_interp((wt,whead), outhead)
        newbg, bfootprint = reproject_interp((bkg_image,head), outhead)        
        fnx,fny = newim.shape

        # Step 3. Scale the image
        #  divide image by "scales"
        newim /= scales[i]
        #  wt = 1/err^2, need to perform same operation on err as on image
        newwt *= scales[i]**2
        
        # Step 4. Break up into bins and save to temporary file
        tid,tfile = tempfile.mkstemp(prefix="timage",dir="/tmp")
        os.close(tid)  # close open file
        tbase = os.path.basename(tfile)
        timfile = "/tmp/"+tbase+"_flx.fits"
        twtfile = "/tmp/"+tbase+"_wt.fits"
        tbgfile = "/tmp/"+tbase+"_bg.fits"

        timhdu = fits.open(timfile)
        twthdu = fits.open(twtfile)
        tbghdu = fits.open(tbgfile)        

        xbin = ybin = 2
        dx = fnx // xbin
        dy = fny // ybin
        
        # Put information in header
        # ONAXIS1, ONAXIS2, SUBX0, SUBX1, SUBY0, SUBY1, SUBNX, SUBNY
        for i in range(xbin):
            x0 = i*dx
            x1 = x0 + dx-1
            if i==(xbin-1): x1=(fnx-1)
            for j in range(ybin):
                y0 = j*dy
                y1 = y0 + dy-1
                if j==(ybin-1): y1=(fny-1)
                newhead = outhead.copy()
                newhead['SCALE'] = scales[i]
                newhead['WEIGHT'] = weights[i]
                newhead['ONAXIS1'] = newhead['NAXIS1']
                newhead['ONAXIS2'] = newhead['NAXIS2']
                newhead['SUBX0'] = x0
                newhead['SUBX1'] = x1
                newhead['SUBNX'] = x1-x0+1               
                newhead['SUBY0'] = y0
                newhead['SUBY1'] = y1
                newhead['SUBNY'] = y1-y0+1
                # Flux
                subim = newim[x0:x1+1,y0:y1+1].copy()
                hdu1 = fits.PrimaryHDU(subim,newhead.copy())
                timhdu.append(hdu1)
                # Weight
                subwt = newwt[x0:x1+1,y0:y1+1].copy()
                hdu1 = fits.PrimaryHDU(subwt,newhead.copy())
                twthdu.append(hdu1)
                # Background
                subbg = newbg[x0:x1+1,y0:y1+1].copy()
                hdu1 = fits.PrimaryHDU(subbg,newhead.copy())
                timhdu.append(hdu1)                
        timhdu.writeto(timfile,overwrite=True)
        timhdu.close()
        twthdu.writeto(twtfile,overwrite=True)
        twthdu.close()
        tbghdu.writeto(tbgfile,overwrite=True)
        tbghdu.close()        
                
        tempfiles.append(timfile)
        tempwtfiles.append(twtfile)
        tempbgfiles.append(tbgfile)

        
    # Step 4. Stack the images
    final = stack(tempfiles,tempwtfiles,tempbgfiles,weights)

    # Delete temporary files

    # Final header
    #  scales, weights, image names, mean backgrounds
    
    
    # OLD NOTES
    #-give list of FITS files (possible with extensions) and mask/noise file info, WCS/output header and coadd method
    #-loop through each file and resample onto final projection (maybe write to temporary file)
    #  do same for error and mask images
    #-perform the coadd method, simplest is just sum/average or median
    #-write output file
    # weighted sum/average/median
    
    # Need to deal with background level and scale
    # calculate background value myself and maybe use photometric zero-point for the scale.
    # does that take the exposure time into account as well?  I think so.
    
    # Use the astropy reproject package


    
    # NEW NOTES
    # When creating the NSC stacks, also create a deep/multi-band stack.

    # coadd steps:
    # -loop over each exposure that overlaps the image
    #   -homogenize masks
    #   -fix "bad" pixels in wt and flux arrays
    #   -fit and subtract 2D background
    #   -resample each overlapping chip onto the final brick WCS (flux preserving)
    #      be careful when interpolating near bad pixels
    #   -save flux/wt/mask/sky to a temporary directory to use later
    # -once all of the resampling is done, figure out the relative weights for all the exposures
    #   and the final scaling
    # -use NSC zeropoints to figure out relative weighting between the exposures
    # -need to be sure that the images are SCALED properly as well (takes into exptime/zeropoint)
    # -depending on the number of overlapping exposures, break up the break into subregions which
    #   will be combined separately.  need to make sure to use consistent weighting/scaling/zero
    #   otherwise there'll be jumps at these boundaries
    # -weighted/scaled combine in each subregion taking the mask and wt image into account properly.
    # -how about outlier rejection?
    # -fpack compress the final stacked images (flux, mask, weight) similar to how the CP files are done
    # -PSF-matching???
    # -with the exposure zpterm and exptime it should be possible to calculate the SCALING of the exposure
    # -should I use that also for the weight?  should take FWHM/SEEING into account.
    #   in allframe_calcweights/getweights I use weight~S/N
    #   S/N goes as sqrt(exptime) and in background-dominated regime S/N ~ 1/FWHM
    #   so maybe something like weight ~ sqrt(scaling)/FWHM
    #   how about teff?  see eqn. 4, pg.10 of Morganson+2018
    #   teff = (FWHM_fid/FwHM)^2 * (B_fid/B) * F_trans
    #   B = background
    #   F_trans = atmospheric transmission relative to a nearly clear night, basically zeropoint
    #   F_trans = 10^(-0.8*(delta_mag-0.2))
    #
    #   teff is the ratio between the actual exposure time and the exposure time necessary to achieve
    #   the same signal-to-noise for point sources observed in nominal conditions. An exposure taken
    #   under “fiducial” conditions has teff = 1.
    #
    #   see section 6.3 for how DES performs the coadds/stacks, they create "chi-mean" coadds of r/i/z
    #   also see Drlica-Wagner+2018, DES Y1 Cosmoogy results
    #
    # -ccdproc.combine
    # https://ccdproc.readthedocs.io/en/latest/image_combination.html#id1
    # -reproject.reproject_interp
    # https://reproject.readthedocs.io/en/stable/
    #   need to check the reprojection algorithms, doesn't support lanczos
    # reproject also has a coadd/mosaicking sofware and can take weights, and can do background matching
    # from reproject.mosaicking import reproject_and_coadd
    # could also use swarp
    # https://www.astromatic.net/pubsvn/software/swarp/trunk/doc/swarp.pdf
