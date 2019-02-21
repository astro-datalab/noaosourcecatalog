pro combine_stripe82_iband_v3

; Combine together the exposure catalogs in Stripe82 for a single band

filter = 'i'

NSC_ROOTDIRS,dldir,mssdir,localdir
dir = dldir+"users/dnidever/nsc/"
str = mrdfits(dir+'instcal/t3b/lists/nsc_instcal_calibrate.fits',1)
str.expdir = file_dirname(strtrim(str.expdir,2))
;str.expdir = strtrim(str.expdir,2)
str.filter = strtrim(str.filter,2)
str.expnum = strtrim(str.expnum,2)

;outfile = str.expdir+'/'+file_basename(str.expdir)+'_cat.fits'
;ind0 = where((str.ra lt 61 or str.ra gt 299) and abs(str.dec) lt 3.0 and str.zpterm ne 0 and str.filter eq filter,nind0)
;medzpterm = median(str[ind0].zpterm)
;sigzpterm = mad(str[ind0].zpterm)
;ind = where((str.ra lt 61 or str.ra gt 299) and abs(str.dec) lt 3.0 and str.zpterm ne 0 and str.filter eq filter and $
;            abs(str.zpterm-medzpterm) lt 3*sigzpterm,nind)
ind = where(str.filter eq filter,nind)

;test = file_test(outfile[gd])
print,strtrim(nind,2),' exposures for BAND=',filter

;; Load the reference data
ref = mrdfits('/dl1/users/dnidever/nsc/Stripe82_v3.fits',1)

for i=0,nind-1 do begin
  base = file_basename(str[ind[i]].expdir)
  ;file = repstr(strtrim(str[ind[i]].metafile,2),'meta','cat')
  file = str[ind[i]].expdir+'/'+file_basename(str[ind[i]].expdir,'_meta.fits')+'_cat.fits'
  if file_test(file) eq 0 then begin
    print,file,' NOT FOUND'
    goto,BOMB
  endif
  cat = mrdfits(file,1,/silent)
  ncat = n_elements(cat)
  add_tag,cat,'expnum','',cat
  cat.expnum = str[ind[i]].expnum
  print,strtrim(i+1,2),' ',base,' ',str[ind[i]].expnum,' ',strtrim(ncat,2)

  ;; Load the Gaia file
  ;gaiafile = str[ind[i]].expdir+'/'+file_basename(str[ind[i]].expdir)+'_GAIA.fits'
  ;if file_test(gaiafile) eq 0 then goto,BOMB
  ;gaia = MRDFITS(gaiafile,1,/silent)
  ;
  ;; Load the 2MASS file
  ;tmassfile = str[ind[i]].expdir+'/'+file_basename(str[ind[i]].expdir)+'_TMASS.fits'
  ;if file_test(tmassfile) eq 0 then goto,BOMB
  ;tmass = MRDFITS(tmassfile,1,/silent)
  ;
  ;; Load the APASS file
  ;apassfile = str[ind[i]].expdir+'/'+file_basename(str[ind[i]].expdir)+'_APASS.fits'
  ;if file_test(apassfile) eq 0 then goto,BOMB
  ;apass = MRDFITS(apassfile,1,/silent)

  ; Matching
  index = lonarr(ncat,3)-1
  dcr = 1.0
  ;SRCMATCH,gaia.ra_icrs,gaia.de_icrs,cat.ra,cat.dec,dcr,gind1,gind2,/sph,count=ngmatch
  ;if ngmatch gt 0 then index[gind2,0] = gind1
  ;SRCMATCH,tmass.raj2000,tmass.dej2000,cat.ra,cat.dec,dcr,tind1,tind2,/sph,count=ntmatch
  ;if ntmatch gt 0 then index[tind2,1] = tind1
  ;SRCMATCH,apass.raj2000,apass.dej2000,cat.ra,cat.dec,dcr,aind1,aind2,/sph,count=namatch
  ;if namatch gt 0 then index[aind2,2] = aind1
  ;gd = where(total(index gt -1,2) eq 3,ngd)
  ;print,'  ',strtrim(ngd,2),' matches to GAIA, 2MASS and APASS'
  ;if ngd eq 0 then begin
  ;  print,'No matches to GAIA, 2MASS and APASS'
  ;  goto,BOMB
  ;endif
  ;cat1 = cat[gd]
  ;gaia1 = gaia[index[gd,0]]
  ;tmass1 = tmass[index[gd,1]]
  ;apass1 = apass[index[gd,2]]
  SRCMATCH,ref.ra,ref.dec,cat.ra,cat.dec,dcr,ind1,ind2,/sph,count=nmatch
  print,'  ',strtrim(nmatch,2),' matches to reference data'
  if nmatch eq 0 then goto,BOMB
  ref1 = ref[ind1]
  cat1 = cat[ind2]


  if n_elements(allcat) eq 0 then begin
    cat0 = cat[0]
    struct_assign,{dum:''},cat0
    allcat = replicate(cat0,2e7)
    ref0 = ref[0]
    struct_assign,{dum:''},ref0
    allref = replicate(ref0,2e7)
    cnt = 0LL
  endif
  tempcat = allcat[cnt:cnt+nmatch-1]
  struct_assign,cat1,tempcat
  allcat[cnt:cnt+nmatch-1] = tempcat
  tempref = allref[cnt:cnt+nmatch-1]
  struct_assign,ref1,tempref
  allref[cnt:cnt+nmatch-1] = tempref
  cnt += nmatch

  ;stop
  BOMB:
endfor
; Trim extra elements
allcat = allcat[0:cnt-1]
allref = allref[0:cnt-1]

; Save the matched catalogs
;save,allcat,allref,file='/dl1/users/dnidever/nsc/instcal/t3b/combine/combine_stripe82_iband_v3.dat'

stop


; Make the plot
!p.font = 0
setdisp
plotdir = '/dl1/users/dnidever/nsc/instcal/t3b/plots/'

file = plotdir+'stripe82_iband_magdiff_color'
ps_open,file,/color,thick=4,/encap
device,/inches,xsize=8.5,ysize=9.5
jk0 = allref.tmass_jmag-allref.tmass_kmag-0.17*allcat.ebv
; SM_IMAG+0.041*COLOR+0.010*EBV-0.003
model_mag = allref.sm_imag + 0.041*jk0 + 0.010*allref.ebv - 0.003
gd = where(allcat.class_star gt 0.8 and allref.tmass_phqual eq 'AAA' and allcat.fwhm_world*3600 lt 2.0,ngd)
hess,jk0[gd],model_mag[gd]-allcat[gd].cmag,dx=0.02,dy=0.02,xr=[-0.1,1.3],yr=[-1,1],/log,xtit='(J-Ks)o',ytit='Model-Mag',tit='i-band'
bindata,jk0[gd],model_mag[gd]-allcat[gd].cmag,xbin,ybin,binsize=0.05,/med,min=0,max=1.2
oplot,xbin,ybin,ps=-1,co=255
gdbin = where(xbin ge 0.3 and xbin le 0.7,ngdbin)
coef = robust_poly_fitq(xbin[gdbin],ybin[gdbin],1)
; -0.0970436    0.0542384
xx = scale_vector(findgen(100),-1,3)
oplot,xx,poly(xx,coef),co=250
oplot,[-1,3],[0,0],linestyle=2,co=255
oplot,[0.3,0.3],[-2,2],linestyle=1,co=255
oplot,[0.7,0.7],[-2,2],linestyle=1,co=255
al_legend,[stringize(coef[1],ndec=3)+'*(J-Ks)!d0!n+'+stringize(coef[0],ndec=3)],textcolor=[250],/top,/left,charsize=1.4
ps_close
ps2png,file+'.eps',/eps
spawn,['epstopdf',file+'.eps'],/noshell
push,plots,file

; versus EBV
file = plotdir+'stripe82_iband_magdiff_ebv'
ps_open,file,/color,thick=4,/encap
device,/inches,xsize=8.5,ysize=9.5
hess,allcat[gd].ebv,model_mag[gd]-allcat[gd].cmag,dx=0.01,dy=0.02,xr=[0,0.8],yr=[-1,1],/log,xtit='E(B-V)',ytit='Model-Mag',tit='i-band'
oplot,[-1,3],[0,0],linestyle=2,co=255
ps_close
ps2png,file+'.eps',/eps
spawn,['epstopdf',file+'.eps'],/noshell
push,plots,file

;; Now use the new equation
file = plotdir+'stripe82_iband_magdiff_color_adjusted'
ps_open,file,/color,thick=4,/encap
device,/inches,xsize=8.5,ysize=9.5
jk0 = allref.tmass_jmag-allref.tmass_kmag-0.17*allcat.ebv
; ORIGINAL: SM_IMAG+0.041*COLOR+0.010*EBV-0.003
; ADJUSTED: SM_IMAG-0.0132*COLOR+0.010*EBV+0.0940
model_mag = allref.sm_imag - 0.0132*jk0 + 0.010*allref.ebv + 0.0940
gd = where(allcat.class_star gt 0.8 and allref.tmass_phqual eq 'AAA' and allcat.fwhm_world*3600 lt 2.0,ngd)
hess,jk0[gd],model_mag[gd]-allcat[gd].cmag,dx=0.02,dy=0.02,xr=[-0.1,1.3],yr=[-1,1],/log,xtit='(J-Ks)o',ytit='Model-Mag',tit='ADJUSTED i-band'
bindata,jk0[gd],model_mag[gd]-allcat[gd].cmag,xbin,ybin,binsize=0.05,/med,min=0,max=1.2
oplot,xbin,ybin,ps=-1,co=255
gdbin = where(xbin ge 0.3 and xbin le 0.7,ngdbin)
coef = robust_poly_fitq(xbin[gdbin],ybin[gdbin],1)
xx = scale_vector(findgen(100),-1,3)
oplot,xx,poly(xx,coef),co=250
oplot,[-1,3],[0,0],linestyle=2,co=255
oplot,[0.3,0.3],[-2,2],linestyle=1,co=255
oplot,[0.7,0.7],[-2,2],linestyle=1,co=255
al_legend,[stringize(coef[1],ndec=3)+'*(J-Ks)!d0!n+'+stringize(coef[0],ndec=3)],textcolor=[250],/top,/left,charsize=1.4
ps_close
ps2png,file+'.eps',/eps
spawn,['epstopdf',file+'.eps'],/noshell
push,plots,file

pdfcombine,plots+'.pdf',plotdir+'stripe82_iband_combine.pdf',/clobber

stop

end
