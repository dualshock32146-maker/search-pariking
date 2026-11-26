[out:json][timeout:120];
area["name"="東京都"]["admin_level"="4"]->.a;
(nwr["amenity"="motorcycle_parking"](area.a);
 nwr["amenity"="parking"]["motorcycle"~"yes|designated"](area.a););
out center tags;
