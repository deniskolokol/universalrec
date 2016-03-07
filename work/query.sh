#!/usr/bin/env bash

echo ""
echo "============ simple user recs ============"
echo ""
echo "Recommendations for user id 10"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "user": "10"
}' http://localhost:8000/queries.json
echo ""


echo ""
echo "Recommendations for user id 14"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "user": "14"
}' http://localhost:8000/queries.json
echo ""

echo ""
echo "Recommendations for user id 10 with negative bias"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "user": "10",
    "event": "dislike",
    "bias": -1
}' http://localhost:8000/queries.json
echo ""

echo ""
echo "============ simple similar item recs ============"
echo ""
echo "Recommendations for item"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "item": "5577899"
}' http://localhost:8000/queries.json
echo ""

echo ""
echo "============ popular item recs only ============"
echo ""
echo "query with no item or user id, ordered by popularity"
echo ""
curl -H "Content-Type: application/json" -d '
{
}' http://localhost:8000/queries.json
echo ""

echo ""
echo "Recommendations for non-existant user: xyz, all from popularity"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "user": "xyz"
}' http://localhost:8000/queries.json
echo ""

echo ""
echo "Recommendations for non-existant item: xyz, all from popularity"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "item": "xyz"
}' http://localhost:8000/queries.json
echo ""

echo ""
echo "Recommendations for no user no item, all from popularity, Jewellery filter"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "fields": [{
        "name": "category",
        "values": ["Jewellery"],
        "bias": -1
    }]
}' http://localhost:8000/queries.json
echo ""


echo ""
echo "Recommendations for no user no item, all from popularity, Jewellery boost"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "fields": [{
        "name": "categories",
        "values": ["Jewellery"],
        "bias": 1.05
    }]
}' http://localhost:8000/queries.json
echo ""


echo ""
echo "Recommendations for no user no item, all from popularity, Jewellery boost, filter by gender"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "fields": [{
        "name": "category",
        "values": ["Jewellery"],
        "bias": 1.05
    }, {
        "name": "gender",
        "values": ["women"],
        "bias": -1
    }]
}' http://localhost:8000/queries.json
echo ""


echo ""
echo "============ query with item and user *EXPERIMENTAL* ============"
# This is experimental, use at your own risk, not well founded in theory
echo ""
echo "Recommendations for no user no item, all from popularity, Tablets boost, Estados Unidos Mexicanos filter"
echo ""
curl -H "Content-Type: application/json" -d '
{
    "user": "14",
    "item": "5577899"
}' http://localhost:8000/queries.json
echo ""
