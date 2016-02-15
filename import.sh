#!/usr/bin/env bash

# exit on any error
set -e

echo ""
echo "Import procedure for FlickThru initial data and events."
echo "If some step fails check that your engine.json file has been restored"
echo "or look for it in 'user-engine.json'"
echo ""

echo "Checking for needed files"
if [ ! -f engine.json ]; then
    echo "File not found: engine.json"
    exit 1
fi

if [ -f user-engine.json ]; then
    echo "File user-engine.json found, this may be an error so we cannot replace engine.json"
    exit 1
fi

# if [ ! -f data/integration-test-expected.txt ]; then
#     echo "File not found: data/integration-test-expected.txt"
#     exit 1
# fi

echo ""
echo "Checking status, should exit if pio is not running."
pio status

echo ""
echo "Checking to see if flickthru_urec app exists, should exit if not."
pio app show flickthru_urec

echo ""
echo "Moving engine.json to user-engine.json"
cp -n engine.json user-engine.json

echo ""
echo "Moving handmade-engine.json to engine.json for integration test."
cp flickthru_urec.json engine.json

echo ""
echo "Cleaning flickthru_urec app data"
yes YES | pio app data-delete flickthru_urec

echo ""
echo "Importing data for integration test"
SRV='http://localhost:7070'
# get the access_key from pio app list
ACCESS_KEY=`pio app show flickthru_urec | grep Key | cut -f 7 -d ' '`
echo -n "Access key: "
echo $ACCESS_KEY
python work/import_sample.py --access_key $ACCESS_KEY --server $SRV --data data/images.zip --events data/likes.zip

echo ""
echo "Building and delpoying model"
pio build
pio train  -- --driver-memory 2g
echo "Model will remain deployed after this test"
nohup pio deploy > deploy.out &
echo "Waiting 20 seconds for the server to start"
sleep 20

echo ""
echo "Running test query, saving results to test.out."
work/query.sh > test.out

echo ""
echo "Restoring engine.json"
mv user-engine.json engine.json

# XXX: manually create data for user's like/dislike and integration-test-expected.txt
# echo ""
# echo "Differences between expected and actual results, none is a passing test:"
# diff data/integration-test-expected.txt test.out

echo ""
echo "Note that the engine is still deployed until killed or this shell exists."
