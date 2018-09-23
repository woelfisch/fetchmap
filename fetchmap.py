#! /usr/bin/python3
#
# fetchmap.py - download tiles from a map tile server and stitch them
# Copyright (C) 2017 Joerg Reuter <jreuter@yaina.de>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License version 2
# as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# example usage:
# fetchmap.py -112.23 34.85 -104.58 40.67 -P A3 -s esri-topo -S /data/maps/naturalearth/ne_10m_roads_north_america.shp -g ~/roadtrip/2017/Roadtrip-2017.gpx -o ~/roadtrip/2017/planned-route.jpg

import argparse
import io
import math
import sys
import os
import os.path
import subprocess
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from inspect import getframeinfo, currentframe
from pathlib import Path

import re
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

try:
    from osgeo import ogr
    import json

    HAVE_GDAL = True
except:
    print("NOTE: GDAL bindings not available, won't render streets")
    HAVE_GDAL = False

try:
    import fontconfig
    HAVE_FONTCONFIG = True
except:
    HAVE_FONTCONFIG = False

DEFAULT_TILESERVER = "wikimedia"
DEFAULT_SHAPEFILE = "/data/maps/naturalearth/ne_10m_roads_north_america.shp"

OVERPASS_URI = "http://overpass-api.de/api/interpreter"
OVERPASS_QUERY = '(node["place"="city"]({bbox});node["place"="town"]({bbox}););out body;'

PaperSizes = {
    "A0": [841, 1189],
    "A1": [594, 841],
    "A2": [420, 594],
    "A3": [297, 420],
    "A4": [210, 297],
    "A5": [148, 210],
    "A6": [105, 148],
    "A7": [74, 105]
}

TileserverList = {
    "natgeo": {
        "style": "natgeo",
        "url": "https://services.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}.jpg",
    },
    "natgeo-us-topo": {
        "style": "natgeo",
        "url": "https://services.arcgisonline.com/arcgis/rest/services/USA_Topo_Maps/MapServer/tile/{z}/{y}/{x}.jpg",
    },

    "esri-terrain": {
        "style": "esri",
        "url": "https://services.arcgisonline.com/arcgis/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}.jpg",
    },
    "esri-topo": {
        "style": "esri",
        "url": "https://services.arcgisonline.com/arcgis/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}.jpg",
    },

    "usgs-relief": {
        "style": "default",
        "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSShadedReliefOnly/MapServer/tile/{z}/{y}/{x}",
    },

    "stamen-terrain": {
        "style": "stamen",
        "url": "http://b.tile.stamen.com/terrain/{z}/{x}/{y}.png",
    },
    "stamen-terrain-background": {
        "style": "stamen",
        "url": "http://b.tile.stamen.com/terrain-background/{z}/{x}/{y}.png",
    },
    "stamen-toner": {
        "style": "stamen",
        "url": "http://b.tile.stamen.com/toner/{z}/{x}/{y}.png",
    },

    "korona-roads": {
        "style": "korona",
        "url": "https://korona.geog.uni-heidelberg.de/tiles/roads/x={x}&y={y}&z={z}",
    },

    "wikimedia-labels": {
        "style": "wikimedia",
        "url": "https://maps.wikimedia.org/osm-intl/{z}/{x}/{y}.png",
    },
    "wikimedia": {
        "style": "wikimedia",
        "url": "https://maps.wikimedia.org/osm/{z}/{x}/{y}.png",
    },
}

Styles = {
    "default": {
        "fonts": {
            # Cabin is provided with the Google Web Fonts, available from http://www.impallari.com/cabin
            "capitals": ("Cabin:style=Bold", 56),
            "cities":("Cabin:style=Bold", 44),
            "towns": ("Cabin:style=Regular", 44),
            "waypoints": ("Cabin:style=Bold", 48),
        },
        "markersizes": {
            "capitals": 14,
            "cities": 10,
            "towns": 8,
        },
        "linewidth": {
            "Interstate": 5,
            "Federal": 5,
            "State": 5,
            "Other": 5,
            "Track": 6,
        },
        "linecolor": {
            "Interstate": "#87CEFA",
            # "Federal": "#FFFF77",
            "Federal": "#B8B8B8",
            "State": "#C8C8C8",
            "Other": "#C8C8C8",
            "Track": "#FF5500",
        },
        "waypointcolor": {
            "background": "#FF5500",
            "text": "#FF0000",
        }
    },
    "stamen": {
        "linewidth": {
            "Interstate": 6,
            "Federal": 6,
            "State": 6,
            "Other": 6,
            "Track": 7,
        },
        "linecolor": {
            # "Interstate": "#A0A0BC",
            "Interstate": "#A0D0A0",
            "Federal": "#E8A8A8",
            "State": "#B0B0B0",
            "Other": "#B0B0B0",
            "Track": "#FF5500",
        },
        "outlinecolor": {
            "Interstate": "#B0F0B0",
            "Federal": "#FFB0FF",
            "State": "white",
            "Other": "white",
            "Track": "red",
        },
        "outlinewidth": {
            "Interstate": 1,
            "Federal": 1,
            "State": 1,
            "Other": 1,
            "Track": 1,
        },
        "mapcoloradjust": {
            "contrast": 0.4,
            "brightness": 1.15,
            "saturation": 1.0,
        }
    }
}

tileshandle = DEFAULT_TILESERVER
tilesserver = TileserverList[tileshandle]
tilesize = 256

Cachedir = "~/.cache/fetchmap"

# filename and directory stuff

def get_path(filename):
    """
    Return the full path of filename (including filename)
    :param filename: the filename 
    :return: 
    """
    return os.path.abspath(os.path.expanduser(filename))


def get_programdir():
    p = get_path(getframeinfo(currentframe()).filename)
    return str(Path(p).resolve().parent)


# Paper size stuff

def get_paper_size(paper="A4", landscape=False, dpi=300, margin=5):
    """
    Get the usable size of a paper format in pixels at a given dpi
    :param paper: one of PaperSizes above
    :param landscape: portrait if False (default), landscape otherwise
    :param dpi: printer resolution (300 dpi by default)
    :param margin: margin with in mm (5 mm by default)
    :return: tupel with, height in mm
    """
    paper = paper.upper()
    if paper not in PaperSizes:
        print("unknown paper format {}".format(paper))
        sys.exit(1)

    size = PaperSizes[paper]
    if landscape:
        size.reverse()

    return round((size[0] - margin) / 25.4 * dpi), round((size[1] - margin) / 25.4 * dpi)


def fits(south, west, north, east, xmax, ymax, zoom):
    """
    Check whether the boundary box fit onto the paper
    :param south: south corner latitude
    :param west:  west corner longitude
    :param north: north corner latitude
    :param east: east corner longitude
    :param xmax: maximum width of paper in tiles
    :param ymax: maximum height of paper in tiles
    :param zoom: zoom factor
    :return: True if it fits
    """
    swx, swy, nex, ney, numx, numy = get_tilerange(south, west, north, east, zoom)
    return (numx <= xmax) and (numy <= ymax)


# conversions to and from tile numbers / pixel on map and geo coordinates

def deg2num(lat_deg, lon_deg, zoom, factor=1):
    """
    Calculate tile number tuple for coordinates
    :param lat_deg: latitude
    :param lon_deg: longitude
    :param zoom: zoom factor
    :param factor: tile size
    :return: tuple of tile numbers, or pixel coordinates on map (for factor == tilesize)
    """
    # print(lat_deg, lon_deg, zoom)
    lat_rad = math.radians(lat_deg)
    n = factor * 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return xtile, ytile


def deg2pixel(lat, lon, zoom):
    """
    Calculate pixel coordinaets from coordinates, wrapper for deg2num()
    :param lat: latitude
    :param lon: longitude
    :param zoom: zoom factor
    :return: pixel coordinate tupel
    """
    return deg2num(lat, lon, zoom, tilesize)


def num2deg(xtile, ytile, zoom):
    """
    Calculate North/West coordinates from tile
    :param xtile: x tile
    :param ytile: y tile
    :param zoom: zoom factor
    :return: latitude, longitude coordinates tupel
    """
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return round(lat_deg, 5), round(lon_deg, 5)


def get_tilerange(south, west, north, east, zoom):
    """
    Get ranges of tiles for bounding box
    :param south: South latitude
    :param west: West longitude
    :param north: North latitude
    :param east: East longitude
    :param zoom: zoom factor
    :return: tupel of corner tiles and number of tiles in each direction
    """
    xtile1, ytile1 = deg2num(south, west, zoom)
    xtile2, ytile2 = deg2num(north, east, zoom)
    numx = abs(xtile2 - xtile1) + 1
    numy = abs(ytile2 - ytile1) + 1
    return xtile1, ytile1, xtile2, ytile2, numx, numy


def get_bbox(x1, y1, x2, y2, zoom):
    """
    Calculate bounding box from tile coordinates
    :param x1: left x tile number
    :param y1: south y tile number
    :param x2: right x tile number
    :param y2: north y tile number
    :param zoom: zoom factor
    :return: tuple with bounding box
    """
    lat1, lon1 = num2deg(x1, y1 + 1, zoom)
    lat2, lon2 = num2deg(x2 + 1, y2, zoom)
    return lat1, lon1, lat2, lon2

def to_int(s):
    """
    Try to get an integer from an OSM kv attribute, to get
    something useful from things like population="19,517 (2010)"
    Note: will fail for non-integer numbers as it removes anything
    that might be a delimiter - US notation has opposite semantics
    of a decimal point and a grouping delimiter.

    :param s: attribute value
    :return: int
    """

    # This should not happen, but we're dealing with OSM here
    if s is None:
        return 0

    try:
        # remove trailing sh*t
        v = re.split(r'[;(\[]', s)[0]
    except:
        v = s

    # let's hope "12 345 000" is actually 12345000
    # and nobody uses thin space or narrow no-break space
    v = int(re.sub(r"[,.'\s]", "", v))
    return int(v)

# Get data from cache or web service

def fetch_tile(x, y, zoom):
    """
    Get a tile from the cache or tile server
    :param x: x tile number
    :param y: y tile number
    :param zoom: zoom factor
    :return: image
    """
    ydir = "{cdir}/{handle}/{zoom}/{x}".format(cdir=Cachedir, handle=tileshandle, zoom=zoom, x=x)
    os.makedirs(ydir, exist_ok=True)
    tilefile = "{}/{}.png".format(ydir, y)
    url = tileserver.replace("${", "{").format(z=zoom, x=x, y=y)
    # print("url={} cachefile={}".format(url, tilefile))
    if os.path.exists(tilefile):
        return Image.open(tilefile).convert("RGBA")

    if args.dryrun:
        return None

    try:
        with urllib.request.urlopen(url) as rfp:
            tiledata = rfp.read()
            with open(tilefile, "wb") as lfp:
                lfp.write(tiledata)
        return Image.open(io.BytesIO(tiledata)).convert("RGBA")
    except:
        print("Can't read tile {z}/{x}/{y}".format(z=zoom, x=x, y=y))
        return None


def fetch_labels(tile_west, tile_south, tile_east, tile_north, zoom):
    """
    Retreive a list of town names (labels) from cache or Overpass server for a given tile range
    :param tile_west: West tile number
    :param tile_south: South tile number
    :param tile_east: East tile number
    :param tile_north: North tile number
    :param zoom: zoom factor
    :return:
    """
    cachefile = "{cdir}/{z}-{w}-{s}-{e}-{n}.osm".format(cdir=Cachedir, z=zoom, w=tile_west, s=tile_south, e=tile_east,
                                                        n=tile_north)
    if os.path.exists(cachefile):
        with open(cachefile, "r") as fp:
            osmdata = fp.read()
        return osmdata

    lat1, lon1, lat2, lon2 = get_bbox(tile_west, tile_south, tile_east, tile_north, zoom)
    bbox = "{y1},{x1},{y2},{x2}".format(y1=lat1, x1=lon1, y2=lat2, x2=lon2)
    params = {
        "data": OVERPASS_QUERY.format(bbox=bbox),
    }

    if args.dryrun:
        return None

    with urllib.request.urlopen(
            urllib.request.Request(OVERPASS_URI, data=urllib.parse.urlencode(params).encode(), method="POST")) as rfp:
        osmdata = rfp.read().decode("UTF-8")
        with open(cachefile, "w") as lfp:
            lfp.write(osmdata)

    return osmdata


# XML parser helper(s)

def latlon_from_attrs(attrs):
    """
    Retrieve lat and lon values from XML tag attributes
    :param attrs: list of attribute (key, val) tuples
    :return: tuple of latitude and longitude values
    """
    lat = None
    lon = None

    for (k, v) in attrs:
        if k == "lat":
            lat = float(v)
        if k == "lon":
            lon = float(v)
    return lat, lon


# Font helper(s)

def get_font_path(font_representation):
    """
    Get the filesystem path to a font described by a fontconfig representation. See
    https://www.freedesktop.org/software/fontconfig/fontconfig-user.html for specs

    This function contains a workaround in case Python-fontconfig isn't available
    :param font_representation: representation of a font, for example "Arial:style=Regular"
    :return: path
    """
    if HAVE_FONTCONFIG:
        fcfont = fontconfig.query(family=font_representation, lang="en")
        if len(fcfont) < 1:
            return None
        return fcfont[0].file

    res = subprocess.check_output(["fc-match", "-f", "%{file}", font_representation + ":stylelang=en"])
    if res:
        return str(res)
    return None

def get_font(fontspec):
    """
    Gets a Pillow ImageFont from the font specification
    :param fontspec: tuple of (font_representation, size), see get_font_path() for details
    :return: ImageFont instance
    """
    fontfile = get_font_path(fontspec[0])
    if not fontfile:
        fontfile = get_font_path("Arial:style=Bold")
        if not fontfile:
            print("WARNING: neither {} nor Arial fonts are available".format(fontspec[0]))
            return ImageFont.load_default()

    return ImageFont.truetype(fontfile, fontspec[1])

class MapDraw:
    """
    Draw lines and labels on a map
    """

    def __init__(self, image, lat, lon, zoom, tilesize=256):
        """
        Constructor
        :param image: PIL image instance
        :param lat: origin latitude
        :param lon: origin longitude
        :param zoom: zoo factor
        :param tilesize: tile size
        """

        self.set_image(image)
        self.zoom = zoom
        xorigin, yorigin = deg2num(lat, lon, zoom)
        self.origin = (xorigin * tilesize, yorigin * tilesize)
        self.cursor = (0, 0)
        self.labels = []
        self.style = Styles["default"]

        self.wpticon = Image.open(Resourcedir + "/waypoint.png").convert("RGBA")
        self.fonts = {}
        self.set_fonts()

    def set_style(self, styleid):
        """
        Set style of overlays
        :param styleid: id of map style
        :return:
        """

        if styleid in Styles:
            st = Styles[styleid]
            for attr in Styles[styleid].keys():
                self.style[attr] = st[attr]
            self.set_fonts()

    def set_fonts(self):
        for font in self.style["fonts"]:
            self.fonts[font] = get_font(self.style["fonts"][font])

    # noinspection PyAttributeOutsideInit,PyAttributeOutsideInit
    def set_image(self, image):
        self.image = image
        self.canvas = ImageDraw.Draw(image)

    def latlon_to_canvas(self, lat, lon):
        """
        Calculate pixel coordinates from lat/lon
        :param lat: latitude
        :param lon: longitude
        :return:
        """
        xabs, yabs = deg2pixel(lat, lon, self.zoom)
        return xabs - self.origin[0], yabs - self.origin[1]

    def move(self, lat, lon):
        """
        Move cursor
        :param lat: latitude
        :param lon: longitude
        :return:
        """
        self.cursor = self.latlon_to_canvas(lat, lon)

    def line(self, lat, lon, linetype="Track", linewidth=None, linecolor=None):
        """
        Draw line from cursor to position
        :param lat: latitude
        :param lon: longitude
        :param linetype: type of line for style
        :param linewidth: width of line, overwrites style data
        :param linecolor: color of line, overwrites style data
        :return:
        """

        if linewidth is None:
            linewidth = canvas.style["linewidth"][linetype]
        if linecolor is None:
            linecolor = canvas.style["linecolor"][linetype]

        pos = self.latlon_to_canvas(lat, lon)
        self.canvas.line([self.cursor, pos], width=linewidth, fill=linecolor)
        self.cursor = pos

    def multiline(self, coords, linetype="Track"):
        """
        Draw multiple line segments
        :param coords: list of coordinate pairs
        :param linetype: type of line for style
        :return:
        """
        if len(coords) < 2: return
        linewidth = canvas.style["linewidth"][linetype]
        linecolor = canvas.style["linecolor"][linetype]
        if "outlinecolor" in canvas.style:
            outlinecolor = canvas.style["outlinecolor"][linetype]
        else:
            outlinecolor = "white"

        if "outlinewidth" in canvas.style:
            outlinewidth = linewidth + canvas.style["outlinewidth"][linetype] * 2
        else:
            outlinewidth = 0

        if outlinewidth > 0:
            self.move(coords[0][1], coords[0][0])
            for c in coords[1:]:
                self.line(c[1], c[0], linewidth=outlinewidth, linecolor=outlinecolor)

        self.move(coords[0][1], coords[0][0])
        for c in coords[1:]:
            self.line(c[1], c[0], linewidth=linewidth, linecolor=linecolor)

    @staticmethod
    def intersects(r1, r2):
        """
        Test if two rectangles intersect
        :param r1: coordinates of the first rectangle, tupel of (x1, y1, x2, y2)
        :param r2: coordinates of the second rectanble
        :return: True if intersect
        """
        return max(r1[0], r2[0]) < min(r1[2], r2[2]) and max(r1[3], r2[3]) < min(r1[1], r2[1])

    def town_label(self, town):
        """
        Draw a town label if it is either capital or does not intersect with a previously drawn
        :param town: dict with town data, keys used currently: name, lat, lon, class
        :return:
        """
        pos = self.latlon_to_canvas(town["lat"], town["lon"])
        font = self.fonts[town["class"]]
        msize = self.style["markersizes"][town["class"]]

        ts = self.canvas.textsize(town["name"], font=font)
        textpos = [pos[0] - ts[0] / 2, pos[1] - ts[1] - msize - 4]
        textbox = (textpos[0], textpos[1], textpos[0] + ts[0], textpos[1] - ts[1])

        for l in self.labels:
            if town["class"] == "capitals":
                break
            if self.intersects(textbox, l):
                return

        self.canvas.text(textpos, town["name"], font=font, fill="black")
        self.labels.append(textbox)

        markerbox = [pos[0] - msize, pos[1] - msize, pos[0] + msize, pos[1] + msize]
        self.canvas.ellipse(markerbox, fill="black", outline="black")
        self.labels.append((markerbox[0], markerbox[3], markerbox[2], markerbox[1]))

        # self.labels.append(markerbox)

    def waypoint(self, lat, lon, text=None):
        """
        Draw a waypoint marker
        :param lat: latitude
        :param lon: longitude
        :param text: label (unused)
        :return:
        """
        x, y = self.latlon_to_canvas(lat, lon)
        y -= self.wpticon.height
        self.image.paste(self.wpticon, (x, y), self.wpticon)

        if text:
            font = self.fonts["waypoints"]
            textcolor = self.style["waypointcolor"]["text"]
            bgcolor = self.style["waypointcolor"]["background"]

            x += self.wpticon.width
            ts = self.canvas.textsize(text, font=font)
            bgpos = (x, y - ts[1] - 4)
            textpos = (bgpos[0] + 4, bgpos[1])

            bg = Image.new("RGBA", (ts[0] + 8, ts[1] + 8), color=bgcolor)
            bg.putalpha(192)
            self.image.paste(bg, bgpos, bg)

            self.canvas.text(textpos, text, font=font, fill=textcolor)


class GPXParser(HTMLParser):
    """
    Parse a GPX file and draw it's track and waypoints on the map
    """

    def __init__(self, draw, features="any"):
        """
        Constructor
        :param draw: canvas
        """
        self.draw = draw
        self.newtrk = True
        self.render_track = features in ["trk", "any"]
        self.render_waypoints = features in ["wpt", "any"]
        self.waypoints = []
        self.waypoint_translation = []

        self.process_metadata = False
        self.process_wpt = False
        self.process_name = False
        self.process_desc = False
        self.wpt_name = None
        self.wpt_desc = None
        self.metadata_desc = None

        super().__init__()

    def handle_starttag(self, tag, attrs):
        if self.render_track:
            if tag == "trkseg":
                self.newtrk = True
            elif tag == "trkpt":
                lat, lon = latlon_from_attrs(attrs)
                if lat is None or lon is None:
                    return

                if self.newtrk:
                    self.draw.move(lat, lon)
                    self.newtrk = False
                else:
                    self.draw.line(lat, lon, linetype="Track")

        if self.render_waypoints:
            if tag == "wpt":
                self.lat, self.lon = latlon_from_attrs(attrs)
                self.process_wpt = True
            elif tag == "metadata":
                self.process_metadata = True

            if self.process_wpt:
                if tag == "name":
                    self.wpt_name = ""
                    self.process_name = True
                elif tag == "desc":
                    self.wpt_desc = ""
                    self.process_desc = True
            elif self.process_metadata:
                if tag == "desc":
                    self.metadata_desc = ""
                    self.process_desc = True

    def handle_endtag(self, tag):
        if self.render_waypoints:
            if tag == "wpt" and self.lat is not None and self.lon is not None:
                # print(self.wpt_name, self.wpt_desc)
                self.waypoints.append((self.lat, self.lon, self.wpt_name))
                self.waypoint_translation.append((self.wpt_name, self.wpt_desc))
                self.wpt_name = None
                self.wpt_desc = None
            elif tag == "name":
                self.process_name = False
            elif tag == "desc":
                if self.process_desc:
                    self.process_desc = False

    def handle_data(self, data):
        if self.process_wpt:
            if self.process_name:
                self.wpt_name += data
            if self.process_desc:
                self.wpt_desc += data
        elif self.process_metadata:
            if self.process_desc:
                self.metadata_desc += data

    def draw_waypoints(self):
        """
        Draw waypoint markers
        :return:
        """
        if self.render_waypoints:
            for wpt in self.waypoints:
                if len(wpt) > 2:
                    text = wpt[2]
                else:
                    text = None
                self.draw.waypoint(wpt[0], wpt[1], text)


class OSMParser(HTMLParser):
    """
    Parse the Overpass output and sort the information according to classes and size of population
    """

    def __init__(self, draw):
        """
        Constructor
        :param draw: canvas
        """
        self.draw = draw
        self.townlist = {
            "capitals": [],
            "cities": [],
            "towns": [],
        }
        self.kv = {}
        self.lat = None
        self.lon = None
        super().__init__()

    def handle_starttag(self, tag, attrs):
        if tag == "node":
            self.kv = {}
            self.lat, self.lon = latlon_from_attrs(attrs)

        if tag == "tag":
            key = None
            val = None
            for (k, v) in attrs:
                if k == "k":
                    key = v
                    val = None
                if k == "v":
                    val = v
            if key is not None:
                self.kv[key] = val

    def handle_endtag(self, tag):
        if tag == "node" and self.lat is not None and self.lon is not None:
            townclass = "towns"
            population = 0

            if "place" in self.kv and self.kv["place"] == "city":
                townclass = "cities"

            if "capital" in self.kv:
                townclass = "capitals"

            if "population" in self.kv:
                try:
                    population = to_int(self.kv["population"])
                except ValueError as e:
                    print("{}: kv={}".format(e, self.kv))

            if "name" in self.kv:
                town = {
                    "name": self.kv["name"],
                    "lat": self.lat,
                    "lon": self.lon,
                    "population": population,
                    "class": townclass,
                }

                self.townlist[townclass].append(town)
            # self.canvas.town_label(self.lat, self.lon, self.kv["name"])
            self.kv = {}

    def get_sorted_towns(self):
        """
        sort the list of towns in each class by size of population (largest first)
        :return: list of towns
        """
        for towntype in self.townlist.keys():
            self.townlist[towntype].sort(key=lambda d: d["population"], reverse=True)
        # print (towntype, self.townlist[towntype])

        return self.townlist


def stitch_map(draw, swx, swy, nex, ney, zoom):
    """
    Retreive and stitch the tiles for range of tiles
    :param draw: canvas
    :param swx: x tile coordinate for the South/West corner tile
    :param swy: y tile coordinate for the South/West corner tile
    :param nex: x tile coordinate for the North/East corner tile
    :param ney: y tile coordinate for the North/East corner tile
    :param zoom: zoo factor
    :return:
    """
    offx = 0
    offy = 0

    for ty in range(ney, swy + 1):
        for tx in range(swx, nex + 1):
            # print(tx, ty, offx, offy)
            tile = fetch_tile(tx, ty, zoom)
            if tile:
                draw.image.paste(tile, (offx, offy))
            offx += tilesize
        offy += tilesize
        offx = 0

    if "mapcoloradjust" in draw.style:
        ta = draw.style["mapcoloradjust"]
        img = draw.image.convert("RGB")
        if "saturation" in ta:
            img = ImageEnhance.Color(img).enhance(ta["saturation"])
        if "contrast" in ta:
            img = ImageEnhance.Contrast(img).enhance(ta["contrast"])
        if "brightness" in ta:
            img = ImageEnhance.Brightness(img).enhance(ta["brightness"])
        draw.set_image(img.convert("RGBA"))


def draw_streets(draw, swx, swy, nex, ney, zoom):
    """
    Get street segments from a shapefile and canvas them on the map
    :param draw: canvas
    :param swx: x tile coordinate for the South/West corner tile
    :param swy: y tile coordinate for the South/West corner tile
    :param nex: x tile coordinate for the North/East corner tile
    :param ney: y tile coordinate for the North/East corner tile
    :param zoom: zoom factor
    :return:
    """
    shapefile = get_path(args.shapefile)
    if os.path.exists(shapefile):
        drv = ogr.GetDriverByName("ESRI Shapefile")
        shp = drv.Open(shapefile, 0)
        shplayer = shp.GetLayer()
        lat1, lon1, lat2, lon2 = get_bbox(swx, swy, nex, ney, zoom)
        wkt = "POLYGON (({lon1} {lat1},{lon1} {lat2},{lon2} {lat2},{lon2} {lat1},{lon1} {lat1}))".format(lon1=lon1,
                                                                                                         lat1=lat1,
                                                                                                         lon2=lon2,
                                                                                                         lat2=lat2)
        shplayer.SetSpatialFilter(ogr.CreateGeometryFromWkt(wkt))

        for feature in shplayer:
            try:
                level = feature.GetField("level")
            except:
                level = feature.GetField("class")

            segment = json.loads(feature.GetGeometryRef().ExportToJson())

            ftype = segment["type"]
            if ftype not in ["LineString", "MultiLineString"]:
                print("Unexpected geometry type {}".format(ftype))
                continue

            if level not in draw.style["linewidth"]:
                print("Missing style for level {}".format(level))
                level = "Other"

            coords = segment["coordinates"]
            if ftype == "LineString":
                draw.multiline(coords, linetype=level)
            elif ftype == "MultiLineString":
                for c in coords:
                    draw.multiline(c, linetype=level)


def draw_gpx_tracks(draw, gpxfiles):
    """
    Draw the tracks for one or more gpxfiles
    :param draw: canvas
    :param gpxfiles: colon-separated list of GPX file names
    :return:
    """

    gpxinstances = []

    if not gpxfiles:
        return gpxinstances

    for gpxfilespec in gpxfiles:
        gfs = gpxfilespec.split(",")
        if len(gfs) > 1 and gfs[0] in ["wpt", "trk", "any"]:
            features = gfs[0]
            gpxfile = ",".join(gfs[1:])
        else:
            features = "any"
            gpxfile = gpxfilespec

        gpxfile = get_path(gpxfile)
        if not os.path.exists(gpxfile):
            print("GPX file »{}« does not exist, ignored".format(gpxfile))
            continue

        with open(gpxfile, "r") as fp:
            gpxparser = GPXParser(draw, features)
            gpxparser.feed(fp.read())
            gpxparser.close()
            gpxinstances.append(gpxparser)

    return gpxinstances


def draw_gpx_waypoints(gpxlist):
    """
    Draw the marker of the GPX tracks
    :param gpxlist: list of GPXParser
    :return:
    """

    if gpxlist is None:
            return

    for gpx in gpxlist:
        gpx.draw_waypoints()


def draw_town_labels(draw, swx, swy, nex, ney, zoom):
    """
    Draw the town markers and names
    :param draw: canvas
    :param swx: x tile coordinate for the South/West corner tile
    :param swy: y tile coordinate for the South/West corner tile
    :param nex: x tile coordinate for the North/East corner tile
    :param ney: y tile coordinate for the North/East corner tile
    :param zoom: zoom factor
    :return:
    """
    osmdata = fetch_labels(swx, swy, nex, ney, zoom)
    if osmdata:
        osm = OSMParser(draw)
        osm.feed(osmdata)
        osm.close()

        towns = osm.get_sorted_towns()
        for townclass in ["capitals", "cities", "towns"]:
            for t in towns[townclass]:
                draw.town_label(t)


def waypoints_as_html(gpxlist, filename, size):
    """
    Generate HTML code to inline map and list all waypoints
    :param gpxlist: list of gpxfiles
    :param filename: output file name
    :param size: map size in pixels
    :return: HTML code
    """
    out = '''<!doctype html>
<html>
    <head>
        <meta http-equiv="Content-type" content="text/html; charset=utf-8">
        <title>{title}</title>
        <style>
             @page {{
                size: auto;
                margin: {margin}mm {margin}mm {margin}mm {margin}mm;
            }}
            img.map {{max-width: 100%}}
            div.map {{page-break-after: always}}
        </style>
    </head>
    <body>
'''

    path = Path(filename)
    out = out.format(title=path.stem, margin=args.margin)

    if path.suffix in [".jpg", ".jpeg", ".png", ".gif", ".tiff", ".tif"]:
        out += '\t<div class="map"><img src="{img}" class="map" alt="{alt}"/></div>\n'.format(
            img=path.name,
            alt=path.stem,
            width=size[0],
            height=size[1])

    for gpx in gpxlist:
        if len(gpx.waypoint_translation) == 0:
            continue

        out += '\t<h1>{}</h1>\n\t<div class="waypoints"><ol>\n'.format(gpx.metadata_desc)
        for poi in gpx.waypoint_translation:
            out += '\t\t<li>'
            if poi[0] is not None:
                out += poi[0]
                if poi[1] is not None:
                    out += '<br>\n\t\t    {}'.format(poi[1])
            else:
                if poi[1] is not None:
                    out += poi[1]
                else:
                    out += '&nbsp;'
            out += '</li>\n'
        out += '\t</ol></div>\n'

    out += '</body>\n</html>'
    return out


def get_cmdline_args():
    """
    Command line handling
    :return: args structure with parameters
    """
    parser = argparse.ArgumentParser(description="create printable map from bounding box")
    parser.add_argument("west", type=float, help="West coordinate of the bounding box")
    parser.add_argument("south", type=float, help="South coordinate of the bounding box")
    parser.add_argument("east", type=float, help="East coordinate of the bounding box")
    parser.add_argument("north", type=float, help="North coordinate of the bounding box")
    parser.add_argument("-P", "--papersize", type=str, default="A4", choices=sorted(PaperSizes.keys()),
                        help="size of paper, e.g. A4")
    parser.add_argument("-l", "--landscape", default=False, help="force landscape orientation", action="store_true")
    parser.add_argument("-p", "--portrait", default=False, help="force portrait orientation", action="store_true")
    parser.add_argument("-d", "--dpi", type=int, default=300, help="print resolution")
    parser.add_argument("-m", "--margin", type=int, default=5, help="width of paper margins in mm")
    parser.add_argument("-z", "--zoom", type=int, default=-1, help="zoom level (mutually exclusive to paper specs)")
    parser.add_argument("-D", "--dryrun", default=False, help="dry run, don't download anything", action="store_true")
    parser.add_argument("-s", "--tilesource", type=str, default=DEFAULT_TILESERVER,
                        choices=sorted(TileserverList.keys()), help="tile server to use")
    parser.add_argument("-t", "--tileserver", type=str, help="URL for the tileserver")
    parser.add_argument("-g", "--gpx", type=str, action="append", help="GPX file: [(trk|wpt|any),]file.gpx - may be specified multiple times")
    parser.add_argument("-S", "--shapefile", type=str, default=DEFAULT_SHAPEFILE, help="shapefile for streets")
    parser.add_argument("-o", "--out", type=str, default="mapfile-{}.jpg", help="name of output file")
    return parser.parse_args()


if __name__ == "__main__":
    """
    Main logic 
    """

    Cachedir = get_path(Cachedir)
    Programdir = get_programdir()
    Resourcedir = Programdir + os.path.sep + "resources"

    args = get_cmdline_args()
    papersize = get_paper_size(args.papersize, False, args.dpi, args.margin)
    maxtilesx, maxtilesy = [papersize[0] / tilesize, papersize[1] / tilesize]

    zoom = args.zoom
    landscape = args.landscape
    found = False

    if args.tileserver:
        tileshandle = "user"
        tileserver = args.tileserver
        style = "default"
    else:
        tileshandle = args.tilesource
        tileserver = TileserverList[args.tilesource]["url"]
        style = TileserverList[args.tilesource]["style"]

    if zoom < 0:
        for zoom in range(18, -1, -1):
            if fits(args.south, args.west, args.north, args.east, maxtilesx, maxtilesy, zoom) and not args.landscape:
                found = True
                break

            if fits(args.south, args.west, args.north, args.east, maxtilesy, maxtilesx, zoom) and not args.portrait:
                landscape = True
                found = True
                break

    if not found:
        print("Paper too small for anything, suitable zoom factor found.")
        sys.exit(1)

    swx, swy, nex, ney, numx, numy = get_tilerange(args.south, args.west, args.north, args.east, zoom)
    imagesize = [numx * tilesize, numy * tilesize]
    outfile = args.out.format(tileshandle)

    print("SW tile: {}/{}/{}.png".format(zoom, swx, swy))
    print("NE tile: {}/{}/{}.png".format(zoom, nex, ney))
    print("Number of x (longitude) tiles: {}".format(numx))
    print("Number of y (latitude) tiles: {}".format(numy))
    print("Size of paper: {}×{}".format(papersize[0], papersize[1]))
    print("Size of graphics: {}×{}".format(imagesize[0], imagesize[1]))

    canvas = MapDraw(Image.new("RGBA", imagesize), args.north, args.west, zoom)
    canvas.set_style(style)

    stitch_map(canvas, swx, swy, nex, ney, zoom)

    if HAVE_GDAL:
        draw_streets(canvas, swx, swy, nex, ney, zoom)

    gpxlist = draw_gpx_tracks(canvas, args.gpx)
    draw_town_labels(canvas, swx, swy, nex, ney, zoom)
    draw_gpx_waypoints(gpxlist)

    if not args.dryrun:
        canvas.image.convert("RGB").save(outfile)

        p = Path(outfile)
        htmlfile = str(p.parent) + os.path.sep + p.stem + ".html"
        with open(htmlfile, "w") as fp:
            fp.write(waypoints_as_html(gpxlist, outfile, imagesize))
    else:
        print(waypoints_as_html(gpxlist, outfile, imagesize))
