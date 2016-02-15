import re
import os
import sys
import json
import random
import subprocess
import predictionio

from dateutil import parser
from datetime import datetime
from optparse import OptionParser

TZ = predictionio.pytz.timezone("Europe/Warsaw")


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
                              '--appid', '1', #XXX: how to get app id?
                              '--input', self.filename])
            self.exporter.close()


def main(filename, **kwargs):
    handler = EventHandler(kwargs['access_key'],
                           kwargs['event_server_uri'])
    clean = kwargs.get('clean', False)
    if clean:
        handler.delete_events()

    events = []
    props = []
    entity_type = 'image'

    # import static data
    with open(kwargs['data_file'], "r+") as f:
        for record in json.load(f):
            entity_id = record['pk']
            properties = record['fields']
            del properties['likes']
            del properties['dislikes']
            handler.create_event(event='$set',
                                 entity_type=entity_type,
                                 entity_id=entity_id,
                                 properties=properties,
                                 **kwargs)
            for key, val in properties.items():
                props.append([str(entity_id), '$set', "%s:%s" % (key, val)])
        f.close()

    # import events like/dislike
    with open(kwargs['event_file'], "r+") as f:
        for record in json.load(f):
            entity_id = record['fields']['user']
            event = 'like' if record['liked'] else 'dislike'
            target_entity_id = record['fields'][entity_type]
            handler.create_event(event=event,
                                 entity_type='user',
                                 entity_id=entity_id,
                                 properties={},
                                 target_entity_id=target_entity_id
                                 target_entity_type=entity_type,
                                 event_time=created_at,
                                 **kwargs)
            events.append([entity_id, event, target_entity_id])
        f.close()

    handler.close()
    if handler.filename is not None:
        print >> sys.stdout, '--\nExported to %s, waiting in queue' % \
                             os.path.abspath(handler.filename)

    # export props and events to text file
    f = open(filename.rsplit('.', 1)[0] + '.txt', 'w+')
    for line in (events + props):
        f.write(','.join(line) + '\n')
    f.close()


if __name__ == '__main__':
    parser = OptionParser(usage="usage: python %prog [OPTIONS]")
    parser.add_option("-s", "--server", action="store", dest="event_server_uri",
                      help="URI of event server")
    parser.add_option("-c", "--access_key", action="store", dest="access_key",
                      help="Access key")
    parser.add_option("-l", "--clean", action="store_true", dest="clean",
                      help="Clean before export")
    parser.add_option("-d", "--data", action="store", dest="data_file",
                      help="Data file with image descriptions")
    parser.add_option("-e", "--event", action="store", dest="event_file",
                      help="File with events 'like/dislike'")
    opts, args = parser.parse_args()
    if not opts.event_server_uri:
        parser.error("URI of event server missing")
    if not opts.access_key:
        parser.error("Access key missinng")
    if not opts.data_file:
        parser.error("Data file with image descriptions missing")
    if not opts.event_file:
        parser.error("File with events 'like/dislike' missinng")

    try:
        main(**vars(opts))
        print 'Done.'
    except IOError as error:
        print >> sys.stderr, error