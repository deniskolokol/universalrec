import re
import os
import sys
import zipfile
import subprocess
import predictionio
from dateutil import parser
from datetime import datetime
from optparse import OptionParser


GENDER_WOMEN = re.compile(r'\/women\/', re.I)
GENDER_MEN = re.compile(r'\/men\/', re.I)
CAT = re.compile(r'\/[a-zA-Z0-9\s\&\-]+\/cat\/', re.I)
COLOR = re.compile(r'\/[a-zA-Z\s\-]+\/image[a-zA-Z0-9]+.jpg\"?$', re.I)
IID = re.compile(r'iid\=[0-9]+', re.I)
TZ = predictionio.pytz.timezone("Australia/Sydney")


# TODO: use tempfile to extract to temp file of the same dir!
def unzip(filename):
    dirname = os.path.dirname(filename)
    with zipfile.ZipFile(filename, "r") as z:
        z.extractall(dirname)
        z.close()
    return filename.replace('.zip', '.csv')


def extract_gen(fileobj, fields, delimiter):
    for line in fileobj:
        yield dict(zip(fields, line.split(delimiter)))
    

def extract(filename, **kwargs):
    if filename.endswith('.zip'):
        filename = unzip(filename)
    delimiter = kwargs.get('delimiter', ',')
    fileobj = open(filename, 'r+')
    fields = [f for f in fileobj.readline().split(delimiter)]
    return extract_gen(fileobj, fields, delimiter)


def ensure_event_time(event_time):
    if event_time is None:
        return datetime.now(TZ)
    try:
        event_time = parser.parse(event_time)
    except ValueError:
        return datetime.now(TZ)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=TZ)
    return event_time


class FeatureExtractor():
    def __init__(self):
        self.raw = {}

    def extract_raw(self, source, keys=None):
        """
        `source` can either be list or dict.
        """
        if isinstance(source, dict):
            keys = list(source.keys())
            source = [source[k] for k in keys]            
        keys = [k.replace('/', '_').strip() for k in keys]
        return dict(zip(keys, source))

    def extract_features(self, source, keys=None):
        self.raw = self.extract_raw(source, keys)
        try:
            return True, {
                'iid': self._extract_iid(),
                'gender': self._extract_gender(),
                'category': self._extract_category(),
                'color': self._extract_color(),
                'brand': self._extract_brand(),
                'description': re.sub(r'^"|"$', '', self.raw['description']),
                'image': re.sub(r'^"|"$', '', self.raw['image']),
                'price': float(re.sub(r'^"?\$|"?$', '', self.raw['price']))
                }
        except Exception as error:
            return False, {'error': error}

    def _extract_gender(self):
        if GENDER_WOMEN.search(self.raw['_url']):
            return 'women'
        if GENDER_MEN.search(self.raw['_url']):
            return 'men'        
        return 'unspecified'

    def _extract_category(self):
        return CAT.findall(self.raw['_url'])[0].split('/')[1]

    def _extract_color(self):
        return COLOR.findall(self.raw['image'])[0].split('/')[1]

    def _extract_brand(self):
        from_link = self.raw['link'].replace('http://www.asos.com/', '') \
                                    .split('/', 2)[1]
        from_link_patt = r'^' + from_link.replace('-', r'\"? (?: \-|\s)?')
        results = re.findall(from_link_patt, self.raw['description'], re.I)
        if len(results) > 0:
            return results[0]
        return from_link

    def _extract_iid(self):
        return int(IID.findall(self.raw['link'])[0].replace('iid=', ''))


class EventHandler(object):
    def __init__(self, access_key, event_server_uri):
        self.client = predictionio.EventClient(access_key, event_server_uri)
        self.exporter = None
        self.filename = None

    def delete_events(self):
        try:
            for event in self.client.get_events():
                self.client.adelete_event(event['eventId'])
        except predictionio.NotFoundError:
            return

    def _do_create_event(self, func, event, entity_type, entity_id,
                         target_entity_type, target_entity_id,
                         properties, event_time):
        return func(event=event,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    target_entity_type=target_entity_type,
                    target_entity_id=target_entity_id,
                    properties=properties,
                    event_time=event_time)

    def create_event(self, event, entity_type, entity_id,
                     target_entity_type=None, target_entity_id=None,
                     properties=None, event_time=None, **kwargs):
        async = kwargs.get('async',  False)
        if async:
            func = self.client.acreate_event
        else:
            func = self.client.create_event
        event_time = ensure_event_time(event_time)
        return self._do_create_event(func, event, entity_type, entity_id,
                                     target_entity_type, target_entity_id,
                                     properties, event_time)

    def _lazy_get_exporter_func(self, **kwargs):
        """kwargs must contain filename"""
        if self.exporter is None:
            self.filename = kwargs['filename']
            self.exporter = predictionio.FileExporter(file_name=self.filename)
        return self.exporter.create_event
        
    def export_event(self, event, entity_type, entity_id,
                     target_entity_type=None, target_entity_id=None,
                     properties=None, event_time=None, **kwargs):
        func = self._lazy_get_exporter_func(**kwargs)
        event_time = ensure_event_time(event_time)
        return self._do_create_event(func, event, entity_type, entity_id,
                                     target_entity_type, target_entity_id,
                                     properties, event_time)

    def close(self):
        if self.exporter is not None:
            subprocess.Popen(['pio', 'import',
                              '--appid', '2', #XXX: how to get app id?
                              '--input', self.filename])
            self.exporter.close()
            print >> sys.stdout, '--\nExported to %s, waiting in queue' % \
                     os.path.abspath(handler.filename)


def main(datafile, eventfile, **kwargs):
    delimiter = kwargs.get('delimiter', ',')
    export_json = kwargs.get('export_json', False)
    clean = kwargs.get('clean', False)
    handler = EventHandler(kwargs['access_key'],
                           kwargs['event_server_uri'])
    clean = kwargs.get('clean', False)
    if clean:
        handler.delete_events()
    events = []
    props = []
    # collect events like/dislike
    # WARNING! `target_entity_id` is a line number,
    #          should be substituted with iid!
    event_records = {}
    for record in extract(eventfile):
        record.update(entity_type='user', target_entity_type='item')
        event_records[record['target_entity_id']] = record
    # import static data
    ln = 0
    extractor = FeatureExtractor()
    for record in extract(datafile):
        # extract features
        success, properties = extractor.extract_features(record)
        if not success:
            print  >> sys.stderr, "[WARN] skipping line %d: %s" % (
                ln, properties['error']
                )
            continue
        # create $set event
        item_id = properties.pop('iid')
        handler.create_event(event='$set',
                             entity_type='item',
                             entity_id=item_id,
                             properties=properties,
                             **kwargs)
        # prepare item properties for export
        for key, val in properties.items():
            props.append([str(item_id), '$set', "%s:%s" % (key, val)])
        # check if this item was liked or disliked
        try:
            event = event_records[str(ln)]
            event['target_entity_id'] = item_id
            handler.create_event(**event)
            events.append([str(event['entity_id']), event['event'],
                           str(event['target_entity_id'])])
        except KeyError:
            pass
        ln += 1

    handler.close()

    # export props and events to text file
    fname = datafile.rsplit('.', 1)[0] + '.txt'
    print '[INFO] Exporting props and events to %s' % fname
    try:
        f = open(fname, 'w+')
        for line in (events + props):
            f.write(','.join(line) + '\n')
        f.close()
    except Exception as error:
        print >> sys.stdout, '[WARN] Cannot export to text file, the exception is %s' % error
        return
    print >> sys.stdout, '[INFO] Export completed.'


if __name__ == '__main__':
    optparser = OptionParser(usage="usage: python %prog [OPTIONS]")
    optparser.add_option("-s", "--server", action="store", dest="event_server_uri",
                         help="URI of event server")
    optparser.add_option("-c", "--access_key", action="store", dest="access_key",
                         help="Access key")
    optparser.add_option("-l", "--clean", action="store_true", dest="clean",
                         help="Clean before export")
    optparser.add_option("-d", "--data", action="store", dest="data_file",
                         help="Data file with image descriptions")
    optparser.add_option("-e", "--events", action="store", dest="event_file",
                         help="File with events 'like/dislike'")
    opts, args = optparser.parse_args()
    if not opts.event_server_uri:
        optparser.error("[WARN] URI of event server missing")
    if not opts.access_key:
        optparser.error("[WARN] Access key missinng")
    if not opts.data_file:
        optparser.error("[WARN] Data file with image descriptions missing")
    if not opts.event_file:
        optparser.error("[WARN] File with events 'like/dislike' missinng")

    datafile = os.path.abspath(opts.data_file)
    eventfile = os.path.abspath(opts.event_file)
    print >> sys.stdout, '[INFO] Importing properties from %s, \n\tevents from %s.' % \
                         (datafile, eventfile)

    main(datafile, eventfile, **vars(opts))
    print >> sys.stdout, '[INFO] Data imported successfully.'
