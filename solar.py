import numpy as np

def solar_pos(year, month, day, hour_local, minute, lat, lon, tz_offset):
    """NOAA solar position. Returns (elevation_deg, azimuth_deg from north, clockwise)."""
    import datetime as dt
    d = dt.date(year, month, day)
    jd = d.toordinal() + 1721424.5  # Julian day at 00:00 UT
    frac = (hour_local + minute/60.0 - tz_offset)/24.0
    jd = jd + frac
    jc = (jd - 2451545.0)/36525.0
    gmls = (280.46646 + jc*(36000.76983 + jc*0.0003032)) % 360
    gmas = 357.52911 + jc*(35999.05029 - 0.0001537*jc)
    ecc  = 0.016708634 - jc*(0.000042037 + 0.0000001267*jc)
    r = np.radians(gmas)
    seq = np.sin(r)*(1.914602 - jc*(0.004817+0.000014*jc)) + np.sin(2*r)*(0.019993-0.000101*jc) + np.sin(3*r)*0.000289
    stl = gmls + seq
    sal = stl - 0.00569 - 0.00478*np.sin(np.radians(125.04 - 1934.136*jc))
    seo = 23 + (26 + ((21.448 - jc*(46.815 + jc*(0.00059 - jc*0.001813))))/60)/60
    oc  = seo + 0.00256*np.cos(np.radians(125.04 - 1934.136*jc))
    decl = np.degrees(np.arcsin(np.sin(np.radians(oc))*np.sin(np.radians(sal))))
    y = np.tan(np.radians(oc/2))**2
    gr = np.radians(gmls); gar = np.radians(gmas)
    eqt = 4*np.degrees(y*np.sin(2*gr) - 2*ecc*np.sin(gar) + 4*ecc*y*np.sin(gar)*np.cos(2*gr)
                       - 0.5*y*y*np.sin(4*gr) - 1.25*ecc*ecc*np.sin(2*gar))
    tst = (hour_local*60 + minute + eqt + 4*lon - 60*tz_offset) % 1440
    ha = tst/4 - 180 if tst/4 >= 0 else tst/4 + 180
    ha = tst/4 - 180
    latr = np.radians(lat); dr = np.radians(decl); har = np.radians(ha)
    cz = np.sin(latr)*np.sin(dr) + np.cos(latr)*np.cos(dr)*np.cos(har)
    cz = np.clip(cz, -1, 1)
    zen = np.degrees(np.arccos(cz))
    elev = 90 - zen
    # azimuth
    den = np.cos(latr)*np.sin(np.radians(zen))
    with np.errstate(invalid='ignore', divide='ignore'):
        ca = (np.sin(latr)*cz - np.sin(dr))/den
    ca = np.clip(ca, -1, 1)
    az = np.degrees(np.arccos(ca))
    az = np.where(ha > 0, (az + 180) % 360, (540 - az) % 360)
    return elev, az

if __name__ == "__main__":
    LAT, LON, TZ = 41.9028, 12.4964, 2  # CEST
    for (m,d,label) in [(6,21,"summer solstice"),(8,1,"Aug 1"),(12,21,"winter solstice")]:
        row=[]
        for h in [8,10,12,13,14,16,18,20]:
            e,a = solar_pos(2026,m,d,h,0,LAT,LON,TZ)
            row.append(f"{h:02d}h el={e:5.1f} az={a:5.1f}")
        print(label); print("   " + " | ".join(row))
