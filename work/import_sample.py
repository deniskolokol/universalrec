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
CID = re.compile(r'cid\=[0-9]+', re.I)
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
        yield dict(zip(fields, line.strip().split(delimiter)))    


def extract(filename, **kwargs):
    if filename.endswith('.zip'):
        filename = unzip(filename)
    delimiter = kwargs.get('delimiter', ',')
    fileobj = open(filename, 'r+')
    fields = [f.strip() for f in fileobj.readline().split(delimiter)]
    return extract_gen(fileobj, fields, delimiter)


def order_list(container, key):
    return sorted(container, key=lambda x: x[key])


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
                'cid': self._extract_cid(),
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

    def _extract_cid(self):
        return int(CID.findall(self.raw['link'])[0].replace('cid=', ''))


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

class Registrator():
    def __init__(self, sign_pos='like', sign_neg='dislike'):
        self.positive = []
        self.negative = []
        self.set_event = []
        self.sign_pos = sign_pos
        self.sign_neg = sign_neg

    def _register_set(self, event):
        """
        Prepares item properties for export.
        """
        item_id = str(event.pop('entity_id'))
        ev = event.pop('event')
        key = event.keys()[0]
        val = ':'.join([str(v) for v in event[key]])
        self.set_event.append([item_id, ev, "%s:%s" % (key, val)])

    def _register_event(self, event):
        data = (
            str(event['entity_id']),
            event['event'],
            str(event['target_entity_id'])
        )
        if event['event'] == self.sign_pos:
            self.positive.append(data)
        elif event['event'] == self.sign_neg:
            self.negative.append(data)
        
    def register(self, event):
        if event['event'] == '$set':
            self._register_set(event)
        else:
            self._register_event(event)

    def complete(self):
        """
        Orders containers for export:
        [
            positive events
            negative events
            set events sorted by item id
        ]        
        """
        self.full_data = []
        self.full_data.extend(order_list(self.positive, 1))
        self.full_data.extend(order_list(self.negative, 1))
        self.full_data.extend(order_list(self.set_event, 0))

    def export(self, filename):
        with open(filename, 'w+') as f:
            for line in self.full_data:
                f.write(','.join(line) + '\n')
            f.close()


def main(datafile, eventfile, **kwargs):
    delimiter = kwargs.get('delimiter', ',')
    export_json = kwargs.get('export_json', False)
    clean = kwargs.get('clean', False)
    dry_run = kwargs.get('dry_run', False)
    handler = EventHandler(kwargs['access_key'],
                           kwargs['event_server_uri'])
    clean = kwargs.get('clean', False)
    if clean:
        handler.delete_events()

    # WARNING! `target_entity_id` is a line number,
    #          should be substituted with iid!
    event_records = {}
    for record in extract(eventfile):
        record.update(entity_type='user', target_entity_type='item')
        event_records[record['target_entity_id']] = record
    # import static data
    ln = 0
    extractor = FeatureExtractor()
    regi = Registrator()
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
        prop = dict((k, [v]) for k, v in properties.items())
        prop = {
            'categories': [
                properties['category'],
                properties['brand'],
                properties['color'],
                properties['gender'],
                properties['description'],
            ],
            'image': [properties['image']],
            'price': [properties['price']]
        }
        for k, v in prop.items():
            if not dry_run:
                handler.create_event(event='$set',
                                     entity_type='item',
                                     entity_id=item_id,
                                     properties={k: v},
                                     **kwargs)
            # prepare item properties for export
            reg_prop = {'event': '$set', 'entity_id': item_id, k: v}
            regi.register(reg_prop)
        ln += 1
        # check if this item was liked or disliked
        try:
            event = event_records[str(ln)]
            event['target_entity_id'] = item_id
        except KeyError:
            continue
        if not dry_run:
            handler.create_event(**event)
        regi.register(event)
        # fake to increase scores
        for user_id in ['10', '14', '8']:
            event.update({'entity_id': user_id})
            if not dry_run:
                handler.create_event(**event)
            regi.register(event)


    handler.close()

    # export props and events to text file
    print '[INFO] Exporting props and events to external file.'
    fname = datafile.rsplit('.', 1)[0] + '.txt'
    regi.complete()
    try:
        regi.export(fname)
    except Exception as error:
        print >> sys.stdout, '[WARN] Cannot export to text file, the exception is %s' % error
        return
    print >> sys.stdout, '[INFO] Export completed: %s' % fname


if __name__ == '__main__':
    optparser = OptionParser(usage="usage: python %prog [OPTIONS]")
    optparser.add_option("-s", "--server", action="store", dest="event_server_uri",
                         help="URI of event server")
    optparser.add_option("-c", "--access_key", action="store", dest="access_key",
                         help="Access key")
    optparser.add_option("-d", "--data", action="store", dest="data_file",
                         help="Data file with image descriptions")
    optparser.add_option("-e", "--events", action="store", dest="event_file",
                         help="File with events 'like/dislike'")
    optparser.add_option("-l", "--clean", action="store_true", dest="clean",
                         help="Clean before export")
    optparser.add_option("-r", "--dry", action="store_true", dest="dry_run",
                         help="Dry run: do not create actual events, only prepare a text file for export")
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
    if not opts.dry_run:
        print >> sys.stdout, '[INFO] Data imported successfully.'
