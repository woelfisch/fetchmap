#! /usr/bin/python3

# Remove rte and trk elements from a GPX file, leave just the waypoints and the metadata
#
# Written 2017 by Joerg Reuter <jreuter@yaina.de>
# CC0 1.0 https://creativecommons.org/publicdomain/zero/1.0/deed.en

import sys
from xml.dom.minidom import parse

if len(sys.argv) < 2:
    print("usage: gpxwaypoints.py in.gpx [out.gpx]")
    sys.exit(1)

if len(sys.argv) > 2:
    outfile = sys.argv[2]
else:
    outfile = None

with parse(sys.argv[1]) as dom:
    for name in ["trk", "rte"]:
        nodes = dom.getElementsByTagName(name)
        for n in nodes:
            parent = n.parentNode
            parent.removeChild(n)

    if outfile is not None:
        with open(sys.argv[2], "w") as fp:
            fp.write(dom.toprettyxml())
    else:
        print(dom.toprettyxml())