# run this first in flickthru virtualenv!

import os
import random

from core.models import Like

from django.db.models import Count


filename = 'likes.csv'
fobj = open(filename, 'w+')
fobj.write('entity_id,event,target_entity_id,event_time\n')
img_index = range(499) # indexes of images to pick from
registered = {}
for rec in Like.objects.order_by('image', 'user', 'liked', 'created_at'):
    try:
        image = registered[str(rec.image.id)]
    except KeyError:
        image = img_index.pop(random.randrange(len(img_index)))
        registered[str(rec.image.id)] = image
    event = 'like' if rec.liked else 'dislike'
    fobj.write('%s,%s,%s,%s\n' % (
        rec.user.id, event, image, rec.created_at.isoformat()
        ))
fobj.close()
print 'Done: %s' % os.path.abspath(filename)
