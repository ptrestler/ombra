import numpy as np, math
LAT0, LON0 = 41.8965, 12.4800
MPERLAT = 111132.0
def mperlon(lat=LAT0): return 111320.0*math.cos(math.radians(lat))
def to_xy(lon, lat):
    return (np.asarray(lon)-LON0)*mperlon(), (np.asarray(lat)-LAT0)*MPERLAT
def to_ll(x, y):
    return np.asarray(x)/mperlon()+LON0, np.asarray(y)/MPERLAT+LAT0
