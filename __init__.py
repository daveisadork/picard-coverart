""" 
A small plugin to download cover art for any releseas that have a
CoverArtLink relation.


Changelog:

    [2009-07-21] Temporary hack to make up for lack of manual cover art feature.
                 Check for local images if no remote images are found.

    [2008-04-15] Refactored the code to be similar to the server code (hartzell, phw)
    
    [2008-03-10] Added CDBaby support (phw)
    
    [2007-09-06] Added Jamendo support (phw)

    [2007-04-24] Moved parsing code into here
                 Swapped to QUrl
                 Moved to a list of urls

    [2007-04-23] Moved it to use the bzr picard
                 Took the hack out
                 Added Amazon ASIN support
                 
    [2007-04-23] Initial plugin, uses a hack that relies on Python being
                 installed and musicbrainz2 for the query.

"""

PLUGIN_NAME = 'Cover Art Downloader'
PLUGIN_AUTHOR = 'Oliver Charles, Philipp Wolfer'
PLUGIN_DESCRIPTION = '''Downloads cover artwork for releases that have a
CoverArtLink.'''
PLUGIN_VERSION = "0.4"
PLUGIN_API_VERSIONS = ["0.9.0", "0.10"]

from PyQt4.QtCore import QUrl
from picard.metadata import register_album_metadata_processor
from picard.ui.options import register_options_page, OptionsPage
from picard.config import BoolOption, IntOption, TextOption
from picard.plugins.coverart.ui_options_coverart import Ui_CoverartOptionsPage
from picard.util import partial
import re
import os
import os.path
import sys
from tempfile import TemporaryFile
from PIL import Image


#
# data transliterated from the perl stuff used to find cover art for the
# musicbrainz server.
# See mb_server/cgi-bin/MusicBrainz/Server/CoverArt.pm
# hartzell --- Tue Apr 15 15:25:58 PDT 2008
coverArtSites = [
    # CD-Baby
    # tested with http://musicbrainz.org/release/1243cc17-b9f7-48bd-a536-b10d2013c938.html
    {
    'regexp': 'http://cdbaby.com/cd/(\w)(\w)(\w*)',
    'imguri': 'http://cdbaby.name/$1/$2/$1$2$3.jpg',
    },
    # Jamendo
    # tested with http://musicbrainz.org/release/2fe63977-bda9-45da-8184-25a4e7af8da7.html
    {
    'regexp': 'http:\/\/(?:www.)?jamendo.com\/(?:[a-z]+\/)?album\/([0-9]+)',
    'imguri': 'http://www.jamendo.com/get/album/id/album/artworkurl/redirect/$1/?artwork_size=0',
    },
    ]

_AMAZON_IMAGE_HOST = 'images.amazon.com'
_AMAZON_IMAGE_PATH = '/images/P/%s.01.LZZZZZZZ.jpg'
_AMAZON_IMAGE_PATH_SMALL = '/images/P/%s.01.MZZZZZZZ.jpg'
_AMAZON_IMAGE_PATH2 = '/images/P/%s.02.LZZZZZZZ.jpg'
_AMAZON_IMAGE_PATH2_SMALL = '/images/P/%s.02.MZZZZZZZ.jpg'

def _coverart_downloaded(album, metadata, release, try_list, data, http, error):
    try:
        if error or len(data) < 0:
            if error:
                album.log.error(str(http.errorString()))
            coverart(album, metadata, release, try_list)
        else:
            metadata.add_image("image/jpeg", data)
            for track in album._new_tracks:
                track.metadata.add_image("image/jpeg", data)
    finally:
        album._requests -= 1
        album._finalize_loading(None)


def coverart(album, metadata, release, try_list=None):
    #if album.config.setting['cover_image_filename']:
        for file in album.iterfiles():
            try:
                dir = os.path.dirname(file.filename)
                cover = 'Cover.jpg'
                img = Image.open(os.path.join(dir, cover))
                if img.size[0] > 500:
                    if img.size[1] > 500:
                        wpercent = (500/float(img.size[0]))
                        hsize = int((float(img.size[1])*float(wpercent)))
                        img.resize((500,hsize), Image.ANTIALIAS).save(os.path.join(dir, 'small' + cover))
                        with open(os.path.join(dir, 'small' + cover)) as artwork:
                            album._requests += 1
                            _coverart_downloaded(album, metadata, release, [], artwork.read(), None, None)
                            os.remove(os.path.join(dir, 'small' + cover))
                else:
                    with open(os.path.join(dir, cover)) as artwork:
                        album._requests += 1
                        _coverart_downloaded(album, metadata, release, [], artwork.read(), None, None)
                
                return
            except IOError:

                # try_list will be None for the first call
                if try_list is None:
                    try_list = []

                    try:
                        for relation_list in release.relation_list:
                            if relation_list.target_type == 'Url':
                                for relation in relation_list.relation:
                                    # Search for cover art on special sites
                                    for site in coverArtSites:
                                        #
                                        # this loop transliterated from the perl stuff used to find cover art for the
                                        # musicbrainz server.
                                        # See mb_server/cgi-bin/MusicBrainz/Server/CoverArt.pm
                                        # hartzell --- Tue Apr 15 15:25:58 PDT 2008
                                        match = re.match(site['regexp'], relation.target)
                                        if match != None:
                                            imgURI = site['imguri']
                                            for i in range(1, len(match.groups())+1 ):
                                                if match.group(i) != None:
                                                    imgURI = imgURI.replace('$' + str(i), match.group(i))
                                            _try_list_append_image_url(try_list, QUrl(imgURI))

                                    # Use the URL of a cover art link directly
                                    if relation.type == 'CoverArtLink':
                                        _try_list_append_image_url(try_list, QUrl(relation.target))
                    except AttributeError:
                        pass

                    if metadata['asin']:
                        try_list.append({'host': _AMAZON_IMAGE_HOST, 'port': 80,
                            'path': _AMAZON_IMAGE_PATH % metadata['asin']
                        })
                        try_list.append({'host': _AMAZON_IMAGE_HOST, 'port': 80,
                            'path': _AMAZON_IMAGE_PATH_SMALL % metadata['asin']
                        })
                        try_list.append({'host': _AMAZON_IMAGE_HOST, 'port': 80,
                            'path': _AMAZON_IMAGE_PATH2 % metadata['asin']
                        })
                        try_list.append({'host': _AMAZON_IMAGE_HOST, 'port': 80,
                            'path': _AMAZON_IMAGE_PATH2_SMALL % metadata['asin']
                        })

                elif len(try_list) > 0:
                    # We still have some items to try!
                    album._requests += 1
                    album.tagger.xmlws.download(
                            try_list[0]['host'], try_list[0]['port'], try_list[0]['path'],
                            partial(_coverart_downloaded, album, metadata, release, try_list[1:]),
                            position=1)

def _try_list_append_image_url(try_list, parsedUrl):
    path = parsedUrl.path()
    if parsedUrl.hasQuery():
        path += '?'+'&'.join(["%s=%s" % (k,v) for k,v in parsedUrl.queryItems()])
    try_list.append({
        'host': str(parsedUrl.host()),
        'port': parsedUrl.port(80),
        'path': str(path)
    })

class CoverartOptionsPage(OptionsPage):

    NAME = "coverart"
    TITLE = "Cover Art"
    PARENT = "plugins"

    options = [
        BoolOption("setting", "Coverart_use_track_tags", False),
        BoolOption("setting", "Coverart_use_artist_tags", False),
        #BoolOption("setting", "Coverart_use_artist_images", False),
        IntOption("setting", "Coverart_min_tag_usage", 15),
        TextOption("setting", "Coverart_ignore_tags", "seen live,favorites"),
        TextOption("setting", "Coverart_join_tags", ""),
    ]

    def __init__(self, parent=None):
        super(CoverartOptionsPage, self).__init__(parent)
        self.ui = Ui_CoverartOptionsPage()
        self.ui.setupUi(self)

    def load(self):
        self.ui.use_track_tags.setChecked(self.config.setting["Coverart_use_track_tags"])
        self.ui.use_artist_tags.setChecked(self.config.setting["Coverart_use_artist_tags"])
        #self.ui.use_artist_images.setChecked(self.config.setting["Coverart_use_artist_images"])
        self.ui.min_tag_usage.setValue(self.config.setting["Coverart_min_tag_usage"])
        self.ui.ignore_tags.setText(self.config.setting["Coverart_ignore_tags"])
        self.ui.join_tags.setEditText(self.config.setting["Coverart_join_tags"])

    def save(self):
        self.config.setting["Coverart_use_track_tags"] = self.ui.use_track_tags.isChecked()
        self.config.setting["Coverart_use_artist_tags"] = self.ui.use_artist_tags.isChecked()
        #self.config.setting["Coverart_use_artist_images"] = self.ui.use_artist_images.isChecked()
        self.config.setting["Coverart_min_tag_usage"] = self.ui.min_tag_usage.value()
        self.config.setting["Coverart_ignore_tags"] = unicode(self.ui.ignore_tags.text())
        self.config.setting["Coverart_join_tags"] = unicode(self.ui.join_tags.currentText())

register_album_metadata_processor(coverart)
register_options_page(CoverartOptionsPage)
