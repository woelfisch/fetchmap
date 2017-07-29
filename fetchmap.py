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
# fetchmap.py fetchmap.py -112.23 34.85 -104.58 40.67 -P A3 -s esri-topo -S /data/maps/naturalearth/ne_10m_roads_north_america.shp -g ~/roadtrip/2017/Roadtrip-2017.gpx -o ~/roadtrip/2017/planned-route.jpg

import argparse
import io
import math
import os
import os.path
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from PIL import Image, ImageDraw, ImageFont

try:
    from osgeo import ogr
    import json

    HAVE_GDAL = True
except:
    HAVE_GDAL = False

DEFAULT_TILESERVER = "wikimedia"
DEFAULT_SHAPEFILE = "/data/maps/naturalearth/ne_10m_roads_north_america.shp"

OVERPASS_URI = "http://overpass-api.de/api/interpreter"
OVERPASS_QUERY = '(node["place"="city"]({bbox});node["place"="town"]({bbox}););out body;'

sizes = {
    "A0": [841, 1189],
    "A1": [594, 841],
    "A2": [420, 594],
    "A3": [297, 420],
    "A4": [210, 297],
    "A5": [148, 210],
    "A6": [105, 148],
    "A7": [74, 105]
}

tileserverlist = {
    "natgeo": "https://services.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}.jpg",
    "esri-terrain": "https://services.arcgisonline.com/arcgis/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}.jpg",
    "esri-topo": "https://services.arcgisonline.com/arcgis/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}.jpg",
    "stamen-terrain": "http://b.tile.stamen.com/terrain/{z}/{x}/{y}.png",
    "stamen-toner": "http://b.tile.stamen.com/toner/{z}/{x}/{y}.png",
    "korona-roads": "https://korona.geog.uni-heidelberg.de/tiles/roads/x={x}&y={y}&z={z}",
    "wikimedia-labels": "https://maps.wikimedia.org/osm-intl/{z}/{x}/{y}.png",
    "wikimedia": "https://maps.wikimedia.org/osm/{z}/{x}/{y}.png",
}

tileshandle = DEFAULT_TILESERVER
tilesserver = tileserverlist[tileshandle]
tilesize = 256

cachedir = "~/.cache/fetchmap"
cachedir = os.path.abspath(os.path.expanduser(cachedir))

def get_paper_size(paper="A4", landscape=False, dpi=300, margin=5):
    paper = paper.upper()
    if paper not in sizes:
        print("unknown paper format {}".format(paper))
        sys.exit(1)

    size = sizes[paper]
    if landscape:
        size.reverse()

    return round((size[0]-margin) / 25.4 * dpi), round((size[1]-margin) / 25.4 * dpi)


def fits(south, west, north, east, xmax, ymax, zoom):
    (swx, swy, nex, ney, numx, numy) = get_tilerange(south, west, north, east, zoom)
    return (numx <= xmax) and (numy <= ymax)


def deg2num(lat_deg, lon_deg, zoom, factor=1):
    # print(lat_deg, lon_deg, zoom)
    lat_rad = math.radians(lat_deg)
    n = factor * 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return xtile, ytile


def deg2pixel(lat, lon, zoom):
    return deg2num(lat, lon, zoom, tilesize)


def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return round(lat_deg, 5), round(lon_deg, 5)


def get_tilerange(south, west, north, east, zoom):
    (xtile1, ytile1) = deg2num(south, west, zoom)
    (xtile2, ytile2) = deg2num(north, east, zoom)
    numx = abs(xtile2 - xtile1) + 1
    numy = abs(ytile2 - ytile1) + 1
    return xtile1, ytile1, xtile2, ytile2, numx, numy


def get_bbox(x1, y1, x2, y2, zoom):
    (lat1, lon1) = num2deg(x1, y1 + 1, zoom)
    (lat2, lon2) = num2deg(x2 + 1, y2, zoom)
    return lat1, lon1, lat2, lon2


def fetch_tile(x, y, zoom):
    ydir = "{cdir}/{handle}/{zoom}/{x}".format(cdir=cachedir, handle=tileshandle, zoom=zoom, x=x)
    os.makedirs(ydir, exist_ok=True)
    tilefile = "{}/{}.png".format(ydir, y)
    url = tileserver.replace("${", "{").format(z=zoom, x=x, y=y)
    # print("url={} cachefile={}".format(url, tilefile))
    if os.path.exists(tilefile):
        return Image.open(tilefile)

    if args.dryrun:
        return None

    try:
        with urllib.request.urlopen(url) as rfp:
            tile = rfp.read()
            with open(tilefile, "wb") as lfp:
                lfp.write(tile)
        return Image.open(io.BytesIO(tile))
    except:
        print("Can't read tile {z}/{x}/{y}".format(z=zoom, x=x, y=y))
        return None


def fetch_labels(tile_west, tile_south, tile_east, tile_north, zoom):
    cachefile = "{cdir}/{z}-{w}-{s}-{e}-{n}.osm".format(cdir=cachedir, z=zoom, w=tile_west, s=tile_south, e=tile_east,
                                                        n=tile_north)
    if os.path.exists(cachefile):
        with open(cachefile, "r") as fp:
            osmdata = fp.read()
        return osmdata

    (lat1, lon1, lat2, lon2) = get_bbox(tile_west, tile_south, tile_east, tile_north, zoom)
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


class MapDraw:
    def __init__(self, image, lat, lon, zoom, tilesize=256):
        self.image = image
        self.zoom = zoom
        self.canvas = ImageDraw.Draw(image)
        (xorigin, yorigin) = deg2num(lat, lon, zoom)
        self.origin = (xorigin * tilesize, yorigin * tilesize)
        self.cursor = (0, 0)

        self.labels = []
        self.fonts = {
            "capitals": ImageFont.truetype("Cabin-Bold", 56),
            "cities": ImageFont.truetype("Cabin-Bold", 44),
            "towns": ImageFont.truetype("Cabin-Regular", 44),
        }
        self.markersizes = {
            "capitals": 14,
            "cities": 10,
            "towns": 8,
        }
        self.linewidth = {
            "Interstate": 5,
            "Federal": 5,
            "State": 5,
            "Other": 5,
            "Track": 6,
        }
        self.linecolor = {
            "Interstate": "#87CEFA",
            # "Federal": "#FFFF77",
            "Federal": "#B8B8B8",
            "State": "#C8C8C8",
            "Other": "#C8C8C8",
            "Track": "#FF5500",
        }

    def latlon_to_canvas(self, lat, lon):
        (xabs, yabs) = deg2pixel(lat, lon, self.zoom)
        return xabs - self.origin[0], yabs - self.origin[1]

    def move(self, lat, lon):
        self.cursor = self.latlon_to_canvas(lat, lon)

    # print(self.cursor)

    def line(self, lat, lon, style="Track"):
        pos = self.latlon_to_canvas(lat, lon)
        self.canvas.line([self.cursor, pos], width=draw.linewidth[style], fill=draw.linecolor[style])
        self.cursor = pos

    # print(self.cursor)

    def multiline(self, coords, style="Track"):
        if len(coords) < 2: return
        self.move(coords[0][1], coords[0][0])
        for c in coords[1:]:
            self.line(c[1], c[0], style=style)

    @staticmethod
    def intersects(r1, r2):
        return max(r1[0], r2[0]) < min(r1[2], r2[2]) and max(r1[3], r2[3]) < min(r1[1], r2[1])

    def town_label(self, town):
        pos = self.latlon_to_canvas(town["lat"], town["lon"])
        font = self.fonts[town["class"]]
        msize = self.markersizes[town["class"]]

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


class GPXTrackParser(HTMLParser):
    def __init__(self, draw):
        self.draw = draw
        self.newtrk = True
        super().__init__()

    def handle_starttag(self, tag, attrs):
        if tag == "trkseg":
            self.newtrk = True
        if tag == "trkpt":
            lat = None
            lon = None

            for (k, v) in attrs:
                if k == "lat":
                    lat = float(v)
                if k == "lon":
                    lon = float(v)

            if lat is None or lon is None:
                return

            if self.newtrk:
                self.draw.move(lat, lon)
                self.newtrk = False
            else:
                self.draw.line(lat, lon, style="Track")


class OSMParser(HTMLParser):
    def __init__(self, draw):
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
            self.lat = None
            self.lon = None
            for (k, v) in attrs:
                if k == "lat":
                    self.lat = float(v)
                if k == "lon":
                    self.lon = float(v)
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

            if "place" in self.kv and self.kv["place"] == "city":
                townclass = "cities"

            if "capital" in self.kv:
                townclass = "capitals"

            if "population" in self.kv:
                population = int(self.kv["population"])
            else:
                population = 0

            if "name" in self.kv:
                town = {
                    "name": self.kv["name"],
                    "lat": self.lat,
                    "lon": self.lon,
                    "population": population,
                    "class": townclass,
                }

                self.townlist[townclass].append(town)
            # self.draw.town_label(self.lat, self.lon, self.kv["name"])
            self.kv = {}

    def get_sorted_towns(self):
        for towntype in self.townlist.keys():
            self.townlist[towntype].sort(key=lambda d: d["population"], reverse=True)
        # print (towntype, self.townlist[towntype])

        return self.townlist


def get_cmdline_args():
    parser = argparse.ArgumentParser(description="create printable map from bounding box")
    parser.add_argument("west", type=float, help="West coordinate of the bounding box")
    parser.add_argument("south", type=float, help="South coordinate of the bounding box")
    parser.add_argument("east", type=float, help="East coordinate of the bounding box")
    parser.add_argument("north", type=float, help="North coordinate of the bounding box")
    parser.add_argument("-P", "--papersize", type=str, default="A4", choices=sorted(sizes.keys()),
                        help="size of paper, e.g. A4")
    parser.add_argument("-l", "--landscape", default=False, help="force landscape orientation", action="store_true")
    parser.add_argument("-p", "--portrait", default=False, help="force portrait orientation", action="store_true")
    parser.add_argument("-d", "--dpi", type=int, default=300, help="print resolution")
    parser.add_argument("-m", "--margin", type=int, default=5, help="width of paper margins in mm")
    parser.add_argument("-z", "--zoom", type=int, default=-1, help="zoom level (mutually exclusive to paper specs)")
    parser.add_argument("-D", "--dryrun", default=False, help="dry run, don't download anything", action="store_true")
    parser.add_argument("-s", "--tilesource", type=str, default=DEFAULT_TILESERVER,
                        choices=sorted(tileserverlist.keys()), help="tile server to use")
    parser.add_argument("-t", "--tileserver", type=str, help="URL for the tileserver")
    parser.add_argument("-g", "--gpx", type=str, help="colon separated list of GPX files")
    parser.add_argument("-S", "--shapefile", type=str, default=DEFAULT_SHAPEFILE, help="shapefile for streets")
    parser.add_argument("-o", "--out", type=str, default="mapfile-{}.jpg", help="name of output file")
    return parser.parse_args()


args = get_cmdline_args()
papersize = get_paper_size(args.papersize, False, args.dpi, args.margin)
maxtilesx, maxtilesy = [papersize[0] / tilesize, papersize[1] / tilesize]

zoom = args.zoom
landscape = args.landscape
found = False

if args.tileserver:
    tileshandle = "user"
    tileserver = args.tileserver
else:
    tileshandle = args.tilesource
    tileserver = tileserverlist[args.tilesource]

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

(swx, swy, nex, ney, numx, numy) = get_tilerange(args.south, args.west, args.north, args.east, zoom)

print("SW tile: {}/{}/{}.png".format(zoom, swx, swy))
print("NE tile: {}/{}/{}.png".format(zoom, nex, ney))
print("Number of x (longitude) tiles: {}".format(numx))
print("Number of y (latitude) tiles: {}".format(numy))
print("Size of paper: {}×{}".format(papersize[0], papersize[1]))
print("Size of graphics: {}×{}".format(numx * tilesize, numy * tilesize))

themap = Image.new("RGB", [numx * tilesize, numy * tilesize])
draw = MapDraw(themap, args.north, args.west, zoom)

offx = 0
offy = 0

for ty in range(ney, swy + 1):
    for tx in range(swx, nex + 1):
        # print(tx, ty, offx, offy)
        tile = fetch_tile(tx, ty, zoom)
        if tile:
            themap.paste(tile, (offx, offy))
        offx += tilesize
    offy += tilesize
    offx = 0

shapefile = os.path.abspath(os.path.expanduser(args.shapefile))
if HAVE_GDAL and os.path.exists(shapefile):
    drv = ogr.GetDriverByName("ESRI Shapefile")
    shp = drv.Open(shapefile, 0)
    shplayer = shp.GetLayer()
    (lat1, lon1, lat2, lon2) = get_bbox(swx, swy, nex, ney, zoom)
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

        if level not in draw.linewidth:
            print("Missing style for level {}".format(level))
            level = "Other"

        coords = segment["coordinates"]
        if ftype == "LineString":
            draw.multiline(coords, style=level)
        elif ftype == "MultiLineString":
            for c in coords:
                draw.multiline(c, style=level)

if args.gpx:
    for gpxfile in args.gpx.split(":"):
        gpxfile = os.path.abspath(os.path.expanduser(gpxfile))
        if not os.path.exists(gpxfile):
            print("GPX file »{}« does not exist, ignored".format(gpxfile))
            continue

        with open(gpxfile, "r") as fp:
            gpxparser = GPXTrackParser(draw)
            gpxparser.feed(fp.read())
            gpxparser.close()

osmdata = fetch_labels(swx, swy, nex, ney, zoom)
if osmdata:
    osm = OSMParser(draw)
    osm.feed(osmdata)
    osm.close()

    towns = osm.get_sorted_towns()
    for townclass in ["capitals", "cities", "towns"]:
        for t in towns[townclass]:
            draw.town_label(t)

if not args.dryrun:
    with open(args.out.format(tileshandle), "wb") as fp:
        themap.save(fp)
