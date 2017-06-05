#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PURPOSE

REFERENCES

REQUIRES

:author: R.K.Garcia <rkgarcia@wisc.edu>
:copyright: 2017 by University of Wisconsin Regents, see AUTHORS for more details
:license: GPLv3, see LICENSE for more details
"""
import os, sys
import logging, unittest
import re
from abc import ABC, abstractmethod
from collections import namedtuple
from datetime import datetime

import gdal
import osr
import numpy as np
from pyproj import Proj

from sift.common import PLATFORM, INFO, INSTRUMENT, KIND
from sift.workspace.goesr_pug import PugL1bTools
from sift.workspace.guidebook import ABI_AHI_Guidebook

LOG = logging.getLogger(__name__)


GUIDEBOOKS = {
    PLATFORM.GOES_16: ABI_AHI_Guidebook,
    PLATFORM.GOES_17: ABI_AHI_Guidebook,
    PLATFORM.HIMAWARI_8: ABI_AHI_Guidebook,
    PLATFORM.HIMAWARI_9: ABI_AHI_Guidebook,
}

import_progress = namedtuple('import_progress', ['uuid', 'stages', 'current_stage', 'completion', 'stage_desc', 'dataset_info', 'data'])
# stages:int, number of stages this import requires
# current_stage:int, 0..stages-1 , which stage we're on
# completion:float, 0..1 how far we are along on this stage
# stage_desc:tuple(str), brief description of each of the stages we'll be doing


def get_guidebook_class(layer_info):
    platform = layer_info.get(INFO.PLATFORM)
    return GUIDEBOOKS[platform]()


def generate_guidebook_metadata(layer_info):
    guidebook = get_guidebook_class(layer_info)
    # also get info for this layer from the guidebook
    gbinfo = guidebook.collect_info(layer_info)
    layer_info.update(gbinfo)  # FUTURE: should guidebook be integrated into DocBasicLayer?

    # add as visible to the front of the current set, and invisible to the rest of the available sets
    layer_info[INFO.COLORMAP] = guidebook.default_colormap(layer_info)
    layer_info[INFO.CLIM] = guidebook.climits(layer_info)
    if INFO.DISPLAY_TIME not in layer_info:
        layer_info[INFO.DISPLAY_TIME] = guidebook._default_display_time(layer_info)
    if INFO.DISPLAY_NAME not in layer_info:
        layer_info[INFO.DISPLAY_NAME] = guidebook._default_display_name(layer_info)

    return layer_info


class aImporter(ABC):
    """
    Instances of this class are typically singletons owned by Workspace.
    They're used to perform background activity for importing large input files.
    """
    def __init__(self, **kwargs):
        super(aImporter, self).__init__()

    @abstractmethod
    def is_relevant(self, source_path=None, source_uri=None):
        """
        return True if this importer is capable of reading this URI.
        """
        return False

    @abstractmethod
    def __call__(self, dest_workspace, dest_wd, dest_uuid, source_path=None, source_uri=None, cache_path=None, **kwargs):
        """
        Yield a series of import_status tuples updating status of the import.
        Typically this is going to run on TheQueue when possible.
        :param dest_cwd: destination directory to place flat files into, may be anywhere inside workspace.cwd
        :param dest_uuid: uuid key to use in reference to this dataset at all LODs - may/not be used in file naming, but should be included in datasetinfo
        :param source_uri: uri to load from
        :param source_path: path to load from (alternative to source_uri)
        :param cache_path: preferred cache path to place data into
        :return: sequence of import_progress, the first and last of which must include data,
                 inbetween updates typically will release data when stages complete and have None for dataset_info and data fields
        """
        raise NotImplementedError('subclass must implement')


class GeoTiffImporter(aImporter):
    """
    GeoTIFF data importer
    """
    def __init__(self, **kwargs):
        super(GeoTiffImporter, self).__init__()

    def is_relevant(self, source_path=None, source_uri=None):
        source = source_path or source_uri
        return True if (source.lower().endswith('.tif') or source.lower().endswith('.tiff')) else False

    @staticmethod
    def _metadata_for_path(pathname):
        meta = {}
        if not pathname:
            return meta

        # Old but still necesary, get some information from the filename instead of the content
        m = re.match(r'HS_H(\d\d)_(\d{8})_(\d{4})_B(\d\d)_([A-Za-z0-9]+).*', os.path.split(pathname)[1])
        if m is not None:
            plat, yyyymmdd, hhmm, bb, scene = m.groups()
            when = datetime.strptime(yyyymmdd + hhmm, '%Y%m%d%H%M')
            plat = PLATFORM('Himawari-{}'.format(int(plat)))
            band = int(bb)
            #
            # # workaround to make old files work with new information
            # from sift.model.guidebook import AHI_HSF_Guidebook
            # if band in AHI_HSF_Guidebook.REFL_BANDS:
            #     standard_name = "toa_bidirectional_reflectance"
            # else:
            #     standard_name = "toa_brightness_temperature"

            meta.update({
                INFO.PLATFORM: plat,
                INFO.BAND: band,
                INFO.INSTRUMENT: INSTRUMENT.AHI,
                INFO.SCHED_TIME: when,
                INFO.OBS_TIME: when,
                INFO.SCENE: scene,
            })
        return meta

    def _check_geotiff_metadata(self, gtiff):
        gtiff_meta = gtiff.GetMetadata()
        # Sanitize metadata from the file to use SIFT's Enums
        if "name" in gtiff_meta:
            gtiff_meta[INFO.DATASET_NAME] = gtiff_meta.pop("name")
        if "platform" in gtiff_meta:
            plat = gtiff_meta.pop("platform")
            gtiff_meta[INFO.PLATFORM] = PLATFORM.from_value(plat)
            if gtiff_meta[INFO.PLATFORM] == PLATFORM.UNKNOWN:
                LOG.warning("Unknown platform being loaded: {}".format(plat))
        if "instrument" in gtiff_meta or "sensor" in gtiff_meta:
            inst = gtiff_meta.pop("sensor", gtiff_meta.pop("instrument", None))
            gtiff_meta[INFO.INSTRUMENT] = INSTRUMENT.from_value(inst)
            if gtiff_meta[INFO.INSTRUMENT] == INSTRUMENT.UNKNOWN:
                LOG.warning("Unknown instrument being loaded: {}".format(inst))
        if "start_time" in gtiff_meta:
            start_time = datetime.strptime(gtiff_meta["start_time"], "%Y-%m-%dT%H:%M:%SZ")
            gtiff_meta[INFO.SCHED_TIME] = start_time
            gtiff_meta[INFO.OBS_TIME] = start_time
            if "end_time" in gtiff_meta:
                end_time = datetime.strptime(gtiff_meta["end_time"], "%Y-%m-%dT%H:%M:%SZ")
                gtiff_meta[INFO.OBS_DURATION] = end_time - start_time
        if "valid_min" in gtiff_meta:
            gtiff_meta["valid_min"] = float(gtiff_meta["valid_min"])
        if "valid_max" in gtiff_meta:
            gtiff_meta["valid_max"] = float(gtiff_meta["valid_max"])
        if "standard_name" in gtiff_meta:
            gtiff_meta[INFO.STANDARD_NAME] = gtiff_meta["standard_name"]
        if "flag_values" in gtiff_meta:
            gtiff_meta["flag_values"] = tuple(int(x) for x in gtiff_meta["flag_values"].split(','))
        if "flag_masks" in gtiff_meta:
            gtiff_meta["flag_masks"] = tuple(int(x) for x in gtiff_meta["flag_masks"].split(','))
        if "flag_meanings" in gtiff_meta:
            gtiff_meta["flag_meanings"] = gtiff_meta["flag_meanings"].split(' ')
        if "units" in gtiff_meta:
            gtiff_meta[INFO.UNITS] = gtiff_meta.pop('units')
        return gtiff_meta

    def get_metadata(self, dest_uuid, source_path=None, source_uri=None, cache_path=None, **kwargs):
        if source_uri is not None:
            raise NotImplementedError("GeoTiffImporter cannot read from URIs yet")
        d = self._metadata_for_path(source_path)
        gtiff = gdal.Open(source_path)

        ox, cw, _, oy, _, ch = gtiff.GetGeoTransform()
        d[INFO.UUID] = dest_uuid
        d[INFO.KIND] = KIND.IMAGE
        d[INFO.ORIGIN_X] = ox
        d[INFO.ORIGIN_Y] = oy
        d[INFO.CELL_WIDTH] = cw
        d[INFO.CELL_HEIGHT] = ch
        # FUTURE: Should the Workspace normalize all input data or should the Image Layer handle any projection?
        srs = osr.SpatialReference()
        srs.ImportFromWkt(gtiff.GetProjection())
        d[INFO.PROJ] = srs.ExportToProj4().strip()  # remove extra whitespace

        # Workaround for previously supported files
        # give them some kind of name that means something
        if INFO.BAND in d:
            d[INFO.DATASET_NAME] = "B{:02d}".format(d[INFO.BAND])
        else:
            # for new files, use this as a basic default
            # FUTURE: Use Dataset name instead when we can read multi-dataset files
            d[INFO.DATASET_NAME] = os.path.split(source_path)[-1]

        d[INFO.PATHNAME] = source_path
        band = gtiff.GetRasterBand(1)
        d[INFO.SHAPE] = rows, cols = (band.YSize, band.XSize)

        # Fix PROJ4 string if it needs an "+over" parameter
        p = Proj(d[INFO.PROJ])
        lon_l, lat_u = p(ox, oy, inverse=True)
        lon_r, lat_b = p(ox + cw * cols, oy + ch * rows, inverse=True)
        if "+over" not in d[INFO.PROJ] and lon_r < lon_l:
            LOG.debug("Add '+over' to geotiff PROJ.4 because it seems to cross the anti-meridian")
            d[INFO.PROJ] += " +over"

        bandtype = gdal.GetDataTypeName(band.DataType)
        if bandtype.lower() != 'float32':
            LOG.warning('attempting to read geotiff files with non-float32 content')

        gtiff_meta = self._check_geotiff_metadata(gtiff)
        d.update(gtiff_meta)
        generate_guidebook_metadata(d)
        return d

    def __call__(self, dest_uuid, source_path=None, source_uri=None, cache_path=None, **kwargs):
        # yield successive levels of detail as we load
        if source_uri is not None:
            raise NotImplementedError("GeoTiffImporter cannot read from URIs yet")
        # Additional metadata that we've learned by loading the data
        gtiff = gdal.Open(source_path)

        # FIXME: read this into a numpy.memmap backed by disk in the workspace
        band = gtiff.GetRasterBand(1)  # FUTURE may be an assumption
        shape = rows, cols = band.YSize, band.XSize
        blockw, blockh = band.GetBlockSize()  # non-blocked files will report [band.XSize,1]

        # shovel that data into the memmap incrementally
        # http://geoinformaticstutorial.blogspot.com/2012/09/reading-raster-data-with-python-and-gdal.html
        fp = open(cache_path, 'wb+')
        img_data = np.memmap(fp, dtype=np.float32, shape=shape, mode='w+')
        # load at an increment that matches the file's tile size if possible
        IDEAL_INCREMENT = 512.0
        increment = min(blockh * int(np.ceil(IDEAL_INCREMENT/blockh)), 2048)
        # FUTURE: consider explicit block loads using band.ReadBlock(x,y) once
        irow = 0
        while irow < rows:
            nrows = min(increment, rows-irow)
            row_data = band.ReadAsArray(0, irow, cols, nrows)
            img_data[irow:irow+nrows,:] = np.require(row_data, dtype=np.float32)
            irow += increment
            status = import_progress(uuid=dest_uuid,
                                       stages=1,
                                       current_stage=0,
                                       completion=float(irow)/float(rows),
                                       stage_desc="importing geotiff",
                                       dataset_info=None,
                                       data=img_data)
            yield status

        # img_data = gtiff.GetRasterBand(1).ReadAsArray()
        # img_data = np.require(img_data, dtype=np.float32, requirements=['C'])  # FIXME: is this necessary/correct?
        # normally we would place a numpy.memmap in the workspace with the content of the geotiff raster band/s here

        # single stage import with all the data for this simple case
        zult = import_progress(uuid=dest_uuid,
                               stages=1,
                               current_stage=0,
                               completion=1.0,
                               stage_desc="done loading geotiff",
                               dataset_info=None,
                               data=img_data)
        yield zult
        # further yields would logically add levels of detail with their own sampling values
        # FIXME: provide example of multiple LOD loading and how datasetinfo dictionary/dictionaries look in that case
        # note that once the coarse data is yielded, we may be operating in another thread - think about that for now?


# map .platform_id in PUG format files to SIFT platform enum
PLATFORM_ID_TO_PLATFORM = {
    'G16': PLATFORM.GOES_16,
    'G17': PLATFORM.GOES_17,
    # hsd2nc export of AHI data as PUG format
    'Himawari-8': PLATFORM.HIMAWARI_8,
    'Himawari-9': PLATFORM.HIMAWARI_9
}


class GoesRPUGImporter(aImporter):
    """
    Import from PUG format GOES-16 netCDF4 files
    """
    def __init__(self, **kwargs):
        super(GoesRPUGImporter, self).__init__()

    @staticmethod
    def _metadata_for_abi_path(abi):
        return {
            INFO.PLATFORM: PLATFORM_ID_TO_PLATFORM[abi.platform],  # e.g. G16
            INFO.BAND: abi.band,
            INFO.INSTRUMENT: INSTRUMENT.ABI,
            INFO.SCHED_TIME: abi.sched_time,
            INFO.DISPLAY_TIME: abi.display_time,
            INFO.SCENE: abi.scene_id,
            INFO.DISPLAY_NAME: abi.display_name
        }

    def is_relevant(self, source_path=None, source_uri=None):
        source = source_path or source_uri
        return True if (source.lower().endswith('.nc') or source.lower().endswith('.nc4')) else False

    def get_metadata(self, dest_uuid, source_path=None, source_uri=None, cache_path=None, **kwargs):
        # yield successive levels of detail as we load
        if source_uri is not None:
            raise NotImplementedError("GoesRPUGImporter cannot read from URIs yet")

        #
        # step 1: get any additional metadata and an overview tile
        #

        d = {}
        # nc = nc4.Dataset(source_path)
        pug = PugL1bTools(source_path)

        d.update(self._metadata_for_abi_path(pug))
        d[INFO.UUID] = dest_uuid
        d[INFO.DATASET_NAME] = os.path.split(source_path)[-1]
        d[INFO.PATHNAME] = source_path
        d[INFO.KIND] = KIND.IMAGE

        d[INFO.PROJ] = pug.proj4_string
        # get nadir-meter-ish projection coordinate vectors to be used by proj4
        y,x = pug.proj_y, pug.proj_x
        d[INFO.ORIGIN_X] = x[0]
        d[INFO.ORIGIN_Y] = y[0]

        midyi, midxi = int(y.shape[0] / 2), int(x.shape[0] / 2)
        # PUG states radiance at index [0,0] extends between coordinates [0,0] to [1,1] on a quadrille
        # centers of pixels are therefore at +0.5, +0.5
        # for a (e.g.) H x W image this means [H/2,W/2] coordinates are image center
        # for now assume all scenes are even-dimensioned (e.g. 5424x5424)
        # given that coordinates are evenly spaced in angular -> nadir-meters space,
        # technically this should work with any two neighbor values
        d[INFO.CELL_WIDTH] = x[midxi+1] - x[midxi]
        d[INFO.CELL_HEIGHT] = y[midyi+1] - y[midyi]

        shape = pug.shape
        d[INFO.SHAPE] = shape
        generate_guidebook_metadata(d)
        LOG.debug(repr(d))
        return d

    def __call__(self, dest_uuid, source_path=None, source_uri=None, cache_path=None, **kwargs):
        pug = PugL1bTools(source_path)
        LOG.info('converting radiance to %s' % pug.bt_or_refl)
        bt_or_refl, image, units = pug.convert_from_nc()  # FIXME expensive
        # overview_image = fixme  # FIXME, we need a properly navigated overview image here

        # we got some metadata, let's yield progress
        # yield    import_progress(uuid=dest_uuid,
        #                          stages=1,
        #                          current_stage=0,
        #                          completion=1.0/3.0,
        #                          stage_desc="calculating imagery",
        #                          dataset_info=d,
        #                          data=image)

        #
        # step 2: read and convert the image data
        #   - in chunks if it's a huge image so we can show progress and/or cancel
        #   - push the data into a workspace memmap
        #   - record the content information in the workspace metadatabase
        #

        # FUTURE as we're doing so, also update coverage array (showing what sections of data are loaded)
        # FUTURE and for some cases the sparsity array, if the data is interleaved (N/A for NetCDF imagery)

        bandtype = np.float32
        LOG.info('caching PUG imagery in workspace %s' % cache_path)
        fp = open(cache_path, 'wb+')
        img_data = np.memmap(fp, dtype=np.float32, shape=pug.shape, mode='w+')
        img_data[:] = np.ma.fix_invalid(image, copy=False, fill_value=np.NAN)  # FIXME: expensive

        yield import_progress(uuid=dest_uuid,
                              stages=1,
                              current_stage=0,
                              completion=1.0,
                              stage_desc="GOES PUG data add to workspace",
                              dataset_info=None,
                              data=img_data)



PATH_TEST_DATA = os.environ.get('TEST_DATA', os.path.expanduser("~/Data/test_files/thing.dat"))

class tests(unittest.TestCase):
    def setUp(self):
        pass

    def test_something(self):
        pass


def _debug(type, value, tb):
    "enable with sys.excepthook = debug"
    if not sys.stdin.isatty():
        sys.__excepthook__(type, value, tb)
    else:
        import traceback, pdb
        traceback.print_exception(type, value, tb)
        # …then start the debugger in post-mortem mode.
        pdb.post_mortem(tb)  # more “modern”


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="PURPOSE",
        epilog="",
        fromfile_prefix_chars='@')
    parser.add_argument('-v', '--verbose', dest='verbosity', action="count", default=0,
                        help='each occurrence increases verbosity 1 level through ERROR-WARNING-INFO-DEBUG')
    parser.add_argument('-d', '--debug', dest='debug', action='store_true',
                        help="enable interactive PDB debugger on exception")
    parser.add_argument('inputs', nargs='*',
                        help="input files to process")
    args = parser.parse_args()

    levels = [logging.ERROR, logging.WARN, logging.INFO, logging.DEBUG]
    logging.basicConfig(level=levels[min(3, args.verbosity)])

    if args.debug:
        sys.excepthook = _debug

    if not args.inputs:
        unittest.main()
        return 0

    for pn in args.inputs:
        pass

    return 0


if __name__ == '__main__':
    sys.exit(main())