# WARNING!
# before run:
# $ virtualenv .../flickthru/bin/activate

import os
import json

from core.models import Like, TitledImage


events = []
for event in Like.objects.all():
    try:
        image = TitledImage.objects.get(id=event.image_id)
    except TitledImage.DoesNotExist:
        continue
    event_data = {
        'model': 'core.like',
        'pk': event.pk,
        'fields': {
            'image': image.media_standard_resolution_url,
            'user': "user."+str(event.user.pk),
            'created_at': event.created_at.isoformat(),
            'liked': event.liked
            }
        }
    events.append(event_data)

fname = 'likes.json'
f = open(fname, 'w+')
json.dump(events, f, indent=4)
f.close()

print os.path.abspath(fname)
