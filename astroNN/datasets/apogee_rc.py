# ---------------------------------------------------------#
#   astroNN.datasets.apogee_rc: APOGEE RC
# ---------------------------------------------------------#

from astropy import units as u
from astropy.io import fits

from astroNN.apogee.downloader import apogee_vac_rc
from astroNN.gaia import extinction_correction
from astroNN.gaia.gaia_shared import mag_to_absmag, mag_to_fakemag


# noinspection PyUnresolvedReferences
def load_apogee_rc(dr=None, metric='distance', extinction=True):
    """
    Load apogee red clumps (absolute magnitude measurement)

    :param dr: Apogee DR
    :type dr: int
    :param metric: which metric you want to get back

                   - "absmag" for k-band absolute magnitude
                   - "fakemag" for k-band fake magnitude
                   - "distance" for distance in parsec
    :type metric: string
    :param extinction: Whether to take extinction into account, only affect when metric is NOT 'distance'
    :type extinction: bool
    :return: numpy array of ra, dec, metrics_array
    :rtype: ndarrays
    :History:
        | 2018-Jan-21 - Written - Henry Leung (University of Toronto)
        | 2018-May-12 - Updated - Henry Leung (University of Toronto)
    """
    fullfilename = apogee_vac_rc(dr=dr)

    with fits.open(fullfilename) as F:
        hdulist = F[1].data
        ra = hdulist['RA']
        dec = hdulist['DEC']
        rc_dist = hdulist['RC_DIST']
        rc_parallax = (1 / rc_dist) * u.mas  # Convert kpc to parallax in mas
        k_mag = hdulist['K']
        if extinction:
            k_mag = extinction_correction(k_mag, hdulist['AK_TARG'])

    if metric == 'distance':
        output = rc_dist * 1000

    elif metric == 'absmag':
        absmag = mag_to_absmag(k_mag, rc_parallax)
        output = absmag

    elif metric == 'fakemag':
        # fakemag requires parallax (mas)
        fakemag = mag_to_fakemag(k_mag, rc_parallax)
        output = fakemag

    else:
        raise ValueError('Unknown metric')

    return ra, dec, output
