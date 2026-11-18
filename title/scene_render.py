"""Measure standalone gallery illustrations against the actual player camera."""
import math

STILLS = {"Ending", "Extras", "Title", "TrialEnd"}


def contain_scale(asset,authored_limit=None,aspect=16/9):
    # CM vcam1 in level0 forces a 3-degree vertical perspective projection.
    # The fixed still-view camera is at -100 and the illustration is at -16.
    height=2*(100-16)*math.tan(math.radians(3/2))
    # The supported Windowed player corrected an 800 x 600 launch request to an 800 x 450 camera surface.
    # Original localized art is an alternate texture and may have different dimensions.
    boxes=[asset]
    if asset.get("localizedGeometry"):boxes.append(asset["localizedGeometry"])
    limits=[]
    for geom in boxes:
        w,h=geom["rectW"],geom["rectH"]
        # Naninovel uses the background actor metadata's PPU (100 for these actors),
        # not the mesh import scale or a uniform ratio based on a presumed 1080p image.
        if w<=0 or h<=0 or aspect<=0:raise ValueError("Invalid illustration geometry")
        limits.append(.96*min(height*aspect*100/w,height*100/h))
    if authored_limit is not None and authored_limit>0:limits.append(authored_limit)
    return min(limits)


def bounds(rect,aspect=16/9):
    left,bottom,right,top,angle=rect
    if not angle:
        return left,bottom,right,top
    sine=abs(math.sin(math.radians(angle)))
    cosine=abs(math.cos(math.radians(angle)))
    w,h=right-left,top-bottom
    dx=(w*cosine+h*sine/aspect)/2
    dy=(w*sine*aspect+h*cosine)/2
    x,y=(left+right)/2,(bottom+top)/2
    return x-dx,y-dy,x+dx,y+dy


def fitted_rects(rects, visible=None):
    """Keep one common projection for all layers; preserve already legible authored framing."""
    if not rects:return []
    shown=rects if visible is None else [r for r,v in zip(rects,visible) if v]
    if not shown:shown=rects
    corners=[bounds(r,aspect) for r in shown for aspect in ((4/3,16/9,21/9) if r[4] else (16/9,))]
    left=min(r[0] for r in corners);bottom=min(r[1] for r in corners)
    right=max(r[2] for r in corners);top=max(r[3] for r in corners)
    width,height=right-left,top-bottom
    extent=max(width,height)
    if extent<=0:raise ValueError("Invalid foreground bounds")
    if min(left,bottom,1-right,1-top)>=0 and extent>=.46:return list(rects)
    # A thumbnail-sized story insert gains readable detail. Larger art keeps its original
    # scale whenever a translation alone can bring the whole illustration into view.
    scale=min(.96/extent,max(1,.55/extent))
    x,y=(left+right)/2,(bottom+top)/2
    dx,dy=scale*width/2,scale*height/2
    nx=max(.02+dx,min(.98-dx,x));ny=max(.02+dy,min(.98-dy,y))
    if extent<.46 or right<=0 or top<=0 or left>=1 or bottom>=1:nx=ny=.5
    return [(nx+(l-x)*scale,ny+(b-y)*scale,nx+(r-x)*scale,ny+(t-y)*scale,angle)
            for l,b,r,t,angle in rects]


def visible_fraction(rect,alpha):
    left,bottom,right,top=bounds(rect)
    if right<=0 or top<=0 or left>=1 or bottom>=1:return 0.0
    if min(left,bottom,1-right,1-top)>=0:return 1.0
    l,b,r,t,ang=rect
    cosine,sine=math.cos(math.radians(ang)),math.sin(math.radians(ang))
    side=math.isqrt(len(alpha));mass=visible=0
    for i,a in enumerate(alpha):
        if a<=16:continue
        px=((i%side+.5)/side-.5)*(r-l)
        py=(.5-(i//side+.5)/side)*(t-b)
        x=(r+l)*.5+px*cosine-py*sine*9/16
        y=(t+b)*.5+px*sine*16/9+py*cosine
        mass+=a
        if 0<=x<=1 and 0<=y<=1:visible+=a
    return visible/mass if mass else 0.0
