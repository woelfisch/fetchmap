# fetchmap

Usage example:

`fetchmap.py fetchmap.py -112.23 34.85 -104.58 40.67 -P A3 -s esri-topo -S /data/maps/naturalearth/ne_10m_roads_north_america.shp -g ~/roadtrip/2017/Roadtrip-2017.gpx -o ~/roadtrip/2017/planned-route.jpg`

Fetchmap downloads and stitches map tiles for a given area from a tile server.
It automatically calculates the zoom factor according to the paper size, margins,
print resolution (default: 300 dpi) and orientation. If no orientation is specified,
it will automatically selects the most suitable one.

Tiles are usually rendered for displays at 96 dpi but not for printed matter 
at 300 dpi, resulting in illegibly small names and invisible streets. To avoid
this, fetchmap can draw city names pulled from OSM data via the Overpass API
and streets from shape files on the map. Also, it can draw GPX tracks.

The script caches all downloads in `~/.cache/fetchmap`, don't forget to clean
the directory up once in a while. The `-D` or `--dryrun` option disables all
downloads (to avoid the ire of the server providers during testing) and output
file writing.

## Requirements

  - Python 3
  - Pillow 1.1.7 or newer
  - GDAL Python bindings (optional)
  - Python-fontconfig 0.5.1 (optional)

## Command line parameters 

    # fetchmap.py -h
    usage: fetchmap.py [-h] [-P {A0,A1,A2,A3,A4,A5,A6,A7}] [-l] [-p] [-d DPI]
                       [-m MARGIN] [-z ZOOM] [-D]
                       [-s {esri-terrain,esri-topo,korona-roads,natgeo,stamen-terrain,stamen-toner,wikimedia,wikimedia-labels}]
                       [-t TILESERVER] [-g GPX] [-S SHAPEFILE] [-o OUT]
                       west south east north
    
    create printable map from bounding box
    
    positional arguments:
      west                  West coordinate of the bounding box
      south                 South coordinate of the bounding box
      east                  East coordinate of the bounding box
      north                 North coordinate of the bounding box
    
    optional arguments:
      -h, --help            show this help message and exit
      -P {A0,A1,A2,A3,A4,A5,A6,A7}, --papersize {A0,A1,A2,A3,A4,A5,A6,A7}
                            size of paper, e.g. A4
      -l, --landscape       force landscape orientation
      -p, --portrait        force portrait orientation
      -d DPI, --dpi DPI     print resolution
      -m MARGIN, --margin MARGIN
                            width of paper margins in mm
      -z ZOOM, --zoom ZOOM  zoom level (mutually exclusive to paper specs)
      -D, --dryrun          dry run, don't download anything
      -s {esri-terrain,esri-topo,korona-roads,natgeo,stamen-terrain,stamen-toner,wikimedia,wikimedia-labels}, --tilesource {esri-terrain,esri-topo,korona-roads,natgeo,stamen-terrain,stamen-toner,wikimedia,wikimedia-labels}
                            tile server to use
      -t TILESERVER, --tileserver TILESERVER
                            URL for the tileserver
       -g GPX, --gpx GPX     GPX file: [(trk|wpt|any),]file.gpx - may be specified
                        multiple times
      -S SHAPEFILE, --shapefile SHAPEFILE
                            shapefile for streets
      -o OUT, --out OUT     name of output file


## Resources

Shape files for the streets are available from [Natural Earth](http://www.naturalearthdata.com/),
the large scale [1:10m Cultural Vectors](http://www.naturalearthdata.com/downloads/10m-cultural-vectors)
road data is suitable, the North America supplement is strongly recommended,
as the regular file seems to miss whole sections of streets in some areas.

Good base map tiles are available (at the time of writing) from
[Wikimedia](https://www.mediawiki.org/wiki/Maps/Technical_Implementation),
[GIScience Universität Heidelberg](https://korona.geog.uni-heidelberg.de/contact.html), or
[ArgGIS](https://services.arcgisonline.com/ArcGIS/rest/services/).

## Notes   

Please excuse the messy code, this suddenly escalated from a simple tile
stitcher to what it is now. Funny how that keeps happening to me.

Thanks to Gregor Leusch for the valuable input and testing on Ubuntu