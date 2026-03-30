"use client";

import React, { useState, useEffect, useRef, memo } from "react";

interface Distributor {
  id: string;
  name: string;
  region: string | null;
  status: string;
  match_count?: number;
  has_violation?: boolean;
  violation_count?: number;
  metadata?: {
    latitude?: number;
    longitude?: number;
    lat?: number;
    lng?: number;
  } | null;
}

interface DealerMapProps {
  distributors: Distributor[];
}

const stateCoordinates: Record<string, [number, number]> = {
  Alabama: [-86.9023, 32.3182], Alaska: [-153.4937, 64.2008],
  Arizona: [-111.0937, 34.0489], Arkansas: [-92.3731, 34.7465],
  California: [-119.4179, 36.7783], Colorado: [-105.3111, 39.0598],
  Connecticut: [-72.7554, 41.5978], Delaware: [-75.5277, 38.9108],
  Florida: [-81.5158, 27.6648], Georgia: [-83.6431, 32.1574],
  Hawaii: [-155.5828, 19.8968], Idaho: [-114.742, 44.0682],
  Illinois: [-89.3985, 40.6331], Indiana: [-86.1349, 40.2672],
  Iowa: [-93.0977, 41.878], Kansas: [-98.4842, 39.0119],
  Kentucky: [-84.27, 37.8393], Louisiana: [-91.9623, 30.9843],
  Maine: [-69.4455, 45.2538], Maryland: [-76.6413, 39.0458],
  Massachusetts: [-71.3824, 42.4072], Michigan: [-85.6024, 44.3148],
  Minnesota: [-94.6859, 46.7296], Mississippi: [-89.3985, 32.3547],
  Missouri: [-91.8318, 37.9643], Montana: [-110.3626, 46.8797],
  Nebraska: [-99.9018, 41.4925], Nevada: [-116.4194, 38.8026],
  "New Hampshire": [-71.5724, 43.1939], "New Jersey": [-74.4057, 40.0583],
  "New Mexico": [-105.8701, 34.5199], "New York": [-75.4999, 43.2994],
  "North Carolina": [-79.0193, 35.7596], "North Dakota": [-101.002, 47.5515],
  Ohio: [-82.9071, 40.4173], Oklahoma: [-97.5164, 35.0078],
  Oregon: [-120.5542, 43.8041], Pennsylvania: [-77.1945, 41.2033],
  "Rhode Island": [-71.4774, 41.5801], "South Carolina": [-81.1637, 33.8361],
  "South Dakota": [-99.9018, 43.9695], Tennessee: [-86.5804, 35.5175],
  Texas: [-99.9018, 31.9686], Utah: [-111.0937, 39.321],
  Vermont: [-72.5778, 44.5588], Virginia: [-78.6569, 37.4316],
  Washington: [-120.7401, 47.7511], "West Virginia": [-80.4549, 38.5976],
  Wisconsin: [-89.6165, 43.7844], Wyoming: [-107.2903, 43.076],
  Northeast: [-73.9857, 40.7484], Southeast: [-84.388, 33.749],
  Midwest: [-87.6298, 41.8781], Southwest: [-112.074, 33.4484],
  West: [-118.2437, 34.0522], Northwest: [-122.3321, 47.6062],
  Central: [-97.7431, 30.2672],
};

const stateAbbreviations: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas",
  CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware",
  FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho",
  IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas",
  KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
  MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma",
  OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah",
  VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia",
  WI: "Wisconsin", WY: "Wyoming",
};

// [city, state_abbrev, longitude, latitude]
const cityData: [string, string, number, number][] = [
  // Alabama
  ["Birmingham", "AL", -86.8025, 33.5207], ["Montgomery", "AL", -86.2999, 32.3668],
  ["Huntsville", "AL", -86.5861, 34.7304], ["Mobile", "AL", -88.0399, 30.6954],
  ["Tuscaloosa", "AL", -87.5692, 33.2098], ["Hoover", "AL", -86.8113, 33.4054],
  ["Dothan", "AL", -85.3905, 31.2232], ["Auburn", "AL", -85.4808, 32.6099],
  ["Decatur", "AL", -86.9833, 34.6059], ["Florence", "AL", -87.6772, 34.7998],
  // Alaska
  ["Anchorage", "AK", -149.9003, 61.2181], ["Fairbanks", "AK", -147.7164, 64.8378],
  ["Juneau", "AK", -134.4197, 58.3005],
  // Arizona
  ["Phoenix", "AZ", -112.074, 33.4484], ["Tucson", "AZ", -110.9747, 32.2226],
  ["Mesa", "AZ", -111.8315, 33.4152], ["Chandler", "AZ", -111.8413, 33.3062],
  ["Scottsdale", "AZ", -111.9261, 33.4942], ["Glendale", "AZ", -112.1859, 33.5387],
  ["Gilbert", "AZ", -111.789, 33.3528], ["Tempe", "AZ", -111.94, 33.4255],
  ["Peoria", "AZ", -112.2374, 33.5806], ["Surprise", "AZ", -112.4473, 33.6292],
  ["Flagstaff", "AZ", -111.6513, 35.1983], ["Yuma", "AZ", -114.6244, 32.6927],
  // Arkansas
  ["Little Rock", "AR", -92.2896, 34.7465], ["Fort Smith", "AR", -94.3985, 35.3859],
  ["Fayetteville", "AR", -94.1574, 36.0626], ["Springdale", "AR", -94.1288, 36.1867],
  ["Jonesboro", "AR", -90.7043, 35.8423], ["North Little Rock", "AR", -92.2671, 34.7695],
  ["Conway", "AR", -92.4421, 35.0887], ["Rogers", "AR", -94.1185, 36.332],
  ["Hot Springs", "AR", -93.0552, 34.5037], ["Pine Bluff", "AR", -92.0032, 34.2284],
  // California
  ["Los Angeles", "CA", -118.2437, 34.0522], ["San Francisco", "CA", -122.4194, 37.7749],
  ["San Diego", "CA", -117.1611, 32.7157], ["San Jose", "CA", -121.8863, 37.3382],
  ["Sacramento", "CA", -121.4944, 38.5816], ["Fresno", "CA", -119.7871, 36.7378],
  ["Long Beach", "CA", -118.1937, 33.77], ["Oakland", "CA", -122.2712, 37.8044],
  ["Bakersfield", "CA", -119.0187, 35.3733], ["Anaheim", "CA", -117.9145, 33.8366],
  ["Santa Ana", "CA", -117.8678, 33.7455], ["Riverside", "CA", -117.3961, 33.9533],
  ["Stockton", "CA", -121.2908, 37.9577], ["Irvine", "CA", -117.8265, 33.6846],
  ["Santa Clarita", "CA", -118.5426, 34.3917], ["San Bernardino", "CA", -117.2898, 34.1083],
  ["Modesto", "CA", -120.9969, 37.6391], ["Fontana", "CA", -117.435, 34.0922],
  ["Oxnard", "CA", -119.1771, 34.1975], ["Moreno Valley", "CA", -117.2308, 33.9425],
  ["Fremont", "CA", -121.9886, 37.5485], ["Santa Rosa", "CA", -122.7141, 38.4405],
  ["Huntington Beach", "CA", -117.9992, 33.6603], ["Visalia", "CA", -119.2921, 36.3302],
  ["Elk Grove", "CA", -121.3716, 38.4088], ["Thousand Oaks", "CA", -118.8376, 34.1706],
  ["Ontario", "CA", -117.6509, 34.0633], ["Concord", "CA", -122.0311, 37.9779],
  ["Simi Valley", "CA", -118.7815, 34.2694], ["Santa Clara", "CA", -121.9552, 37.3541],
  ["Vallejo", "CA", -122.2566, 38.1041], ["Palmdale", "CA", -118.1165, 34.5794],
  ["Lancaster", "CA", -118.1365, 34.6868], ["Rancho Cucamonga", "CA", -117.5931, 34.1064],
  ["Roseville", "CA", -121.288, 38.7521], ["Chula Vista", "CA", -117.0842, 32.6401],
  ["Temecula", "CA", -117.1484, 33.4936], ["Pasadena", "CA", -118.1445, 34.1478],
  ["Redding", "CA", -122.3917, 40.5865], ["Carlsbad", "CA", -117.3506, 33.1581],
  // Colorado
  ["Denver", "CO", -104.9903, 39.7392], ["Colorado Springs", "CO", -104.8214, 38.8339],
  ["Aurora", "CO", -104.8319, 39.7294], ["Fort Collins", "CO", -105.0844, 40.5853],
  ["Lakewood", "CO", -105.0844, 39.7047], ["Thornton", "CO", -104.9719, 39.868],
  ["Pueblo", "CO", -104.6091, 38.2545], ["Boulder", "CO", -105.2705, 40.015],
  ["Grand Junction", "CO", -108.5507, 39.0639], ["Greeley", "CO", -104.7091, 40.4233],
  ["Loveland", "CO", -105.0749, 40.3978], ["Longmont", "CO", -105.1019, 40.1672],
  // Connecticut
  ["Bridgeport", "CT", -73.1952, 41.1865], ["New Haven", "CT", -72.9279, 41.3083],
  ["Stamford", "CT", -73.5387, 41.0534], ["Hartford", "CT", -72.6851, 41.7658],
  ["Waterbury", "CT", -73.0515, 41.5582], ["Norwalk", "CT", -73.4079, 41.1176],
  ["Danbury", "CT", -73.454, 41.3948], ["New Britain", "CT", -72.7795, 41.6612],
  // Delaware
  ["Wilmington", "DE", -75.5398, 39.7391], ["Dover", "DE", -75.5243, 39.1582],
  ["Newark", "DE", -75.7496, 39.6837],
  // Florida
  ["Miami", "FL", -80.1918, 25.7617], ["Orlando", "FL", -81.3792, 28.5383],
  ["Tampa", "FL", -82.4572, 27.9506], ["Jacksonville", "FL", -81.6557, 30.3322],
  ["St. Petersburg", "FL", -82.6403, 27.7676], ["Tallahassee", "FL", -84.2807, 30.4383],
  ["Fort Lauderdale", "FL", -80.1373, 26.1224], ["Cape Coral", "FL", -81.9495, 26.5629],
  ["Port St. Lucie", "FL", -80.3582, 27.2731], ["Hialeah", "FL", -80.2781, 25.8576],
  ["Hollywood", "FL", -80.1494, 26.0112], ["Gainesville", "FL", -82.3248, 29.6516],
  ["Coral Springs", "FL", -80.2706, 26.2712], ["Clearwater", "FL", -82.8001, 27.9659],
  ["Palm Bay", "FL", -80.5887, 28.0345], ["Lakeland", "FL", -81.9498, 28.0395],
  ["West Palm Beach", "FL", -80.0534, 26.7153], ["Sarasota", "FL", -82.5308, 27.3364],
  ["Ocala", "FL", -82.1401, 29.1872], ["Pensacola", "FL", -87.2169, 30.4213],
  ["Fort Myers", "FL", -81.8723, 26.6406], ["Daytona Beach", "FL", -81.0228, 29.2108],
  ["Naples", "FL", -81.7948, 26.142], ["Boca Raton", "FL", -80.0831, 26.3587],
  ["Kissimmee", "FL", -81.4428, 28.292], ["Deltona", "FL", -81.2637, 28.9005],
  // Georgia
  ["Atlanta", "GA", -84.388, 33.749], ["Augusta", "GA", -81.9651, 33.4735],
  ["Savannah", "GA", -81.0998, 32.0809], ["Athens", "GA", -83.3771, 33.951],
  ["Sandy Springs", "GA", -84.3733, 33.9304], ["Roswell", "GA", -84.3613, 34.0232],
  ["Macon", "GA", -83.6324, 32.8407], ["Johns Creek", "GA", -84.1983, 34.0289],
  ["Albany", "GA", -84.1557, 31.5785], ["Columbus", "GA", -84.9877, 32.461],
  ["Alpharetta", "GA", -84.2941, 34.0754], ["Marietta", "GA", -84.5497, 33.9526],
  ["Valdosta", "GA", -83.2785, 30.8327],
  // Hawaii
  ["Honolulu", "HI", -157.8583, 21.3069], ["Pearl City", "HI", -157.975, 21.3972],
  ["Hilo", "HI", -155.09, 19.7297], ["Kailua", "HI", -157.7498, 21.4022],
  // Idaho
  ["Boise", "ID", -116.2023, 43.615], ["Meridian", "ID", -116.3915, 43.6121],
  ["Nampa", "ID", -116.5635, 43.5407], ["Idaho Falls", "ID", -112.0341, 43.4666],
  ["Pocatello", "ID", -112.4455, 42.8621], ["Coeur d'Alene", "ID", -116.7805, 47.6777],
  ["Twin Falls", "ID", -114.4601, 42.5558], ["Lewiston", "ID", -117.0124, 46.4165],
  // Illinois
  ["Chicago", "IL", -87.6298, 41.8781], ["Aurora", "IL", -88.3201, 41.7606],
  ["Rockford", "IL", -89.094, 42.2711], ["Joliet", "IL", -88.0817, 41.525],
  ["Naperville", "IL", -88.1535, 41.7508], ["Springfield", "IL", -89.6501, 39.7817],
  ["Peoria", "IL", -89.589, 40.6936], ["Elgin", "IL", -88.2825, 42.0354],
  ["Champaign", "IL", -88.2434, 40.1164], ["Bloomington", "IL", -88.9937, 40.4842],
  ["Decatur", "IL", -88.9548, 39.8403], ["Evanston", "IL", -87.6876, 42.0451],
  ["Schaumburg", "IL", -88.0834, 42.0334], ["Waukegan", "IL", -87.8448, 42.3636],
  // Indiana
  ["Indianapolis", "IN", -86.1581, 39.7684], ["Fort Wayne", "IN", -85.1394, 41.0793],
  ["Evansville", "IN", -87.5711, 37.9716], ["South Bend", "IN", -86.252, 41.6764],
  ["Carmel", "IN", -86.118, 39.9784], ["Fishers", "IN", -85.9553, 39.9568],
  ["Bloomington", "IN", -86.5264, 39.1653], ["Hammond", "IN", -87.5, 41.5834],
  ["Terre Haute", "IN", -87.4139, 39.4667], ["Muncie", "IN", -85.3864, 40.1934],
  ["Lafayette", "IN", -86.8753, 40.4167], ["Kokomo", "IN", -86.1336, 40.4867],
  // Iowa
  ["Des Moines", "IA", -93.6091, 41.5868], ["Cedar Rapids", "IA", -91.6656, 41.978],
  ["Davenport", "IA", -90.5776, 41.5236], ["Sioux City", "IA", -96.4003, 42.4999],
  ["Iowa City", "IA", -91.5302, 41.6611], ["Waterloo", "IA", -92.3449, 42.493],
  ["Council Bluffs", "IA", -95.8608, 41.2619], ["Ames", "IA", -93.6199, 42.0347],
  ["Dubuque", "IA", -90.6646, 42.5006], ["West Des Moines", "IA", -93.7113, 41.5519],
  // Kansas
  ["Wichita", "KS", -97.3301, 37.6872], ["Overland Park", "KS", -94.6708, 38.9822],
  ["Kansas City", "KS", -94.6275, 39.1141], ["Olathe", "KS", -94.8191, 38.8814],
  ["Topeka", "KS", -95.6752, 39.0473], ["Lawrence", "KS", -95.2353, 38.9717],
  ["Manhattan", "KS", -96.5717, 39.1836], ["Salina", "KS", -97.6114, 38.8403],
  // Kentucky
  ["Louisville", "KY", -85.7585, 38.2527], ["Lexington", "KY", -84.5037, 38.0406],
  ["Bowling Green", "KY", -86.4436, 36.9903], ["Owensboro", "KY", -87.1112, 37.7719],
  ["Covington", "KY", -84.5085, 39.0837], ["Frankfort", "KY", -84.8733, 38.2009],
  ["Richmond", "KY", -84.2947, 37.7479], ["Paducah", "KY", -88.6001, 37.0834],
  // Louisiana
  ["New Orleans", "LA", -90.0715, 29.9511], ["Baton Rouge", "LA", -91.1403, 30.4515],
  ["Shreveport", "LA", -93.7502, 32.5252], ["Lafayette", "LA", -92.0198, 30.2241],
  ["Lake Charles", "LA", -93.2174, 30.2266], ["Monroe", "LA", -92.1193, 32.5093],
  ["Alexandria", "LA", -92.4451, 31.3113], ["Houma", "LA", -90.7195, 29.5958],
  // Maine
  ["Portland", "ME", -70.2553, 43.6591], ["Lewiston", "ME", -70.2148, 44.1004],
  ["Bangor", "ME", -68.7712, 44.8016], ["Augusta", "ME", -69.7795, 44.3106],
  // Maryland
  ["Baltimore", "MD", -76.6122, 39.2904], ["Silver Spring", "MD", -77.0261, 38.991],
  ["College Park", "MD", -76.9369, 38.9807], ["Frederick", "MD", -77.4105, 39.4143],
  ["Rockville", "MD", -77.1528, 39.084], ["Gaithersburg", "MD", -77.2014, 39.1434],
  ["Annapolis", "MD", -76.4922, 38.9784], ["Hagerstown", "MD", -77.72, 39.6418],
  ["Salisbury", "MD", -75.5999, 38.3607],
  // Massachusetts
  ["Boston", "MA", -71.0589, 42.3601], ["Worcester", "MA", -71.7589, 42.2626],
  ["Springfield", "MA", -72.5898, 42.1015], ["Cambridge", "MA", -71.1097, 42.3736],
  ["Lowell", "MA", -71.3162, 42.6334], ["Brockton", "MA", -71.0202, 42.0834],
  ["New Bedford", "MA", -70.934, 41.6362], ["Quincy", "MA", -71.0025, 42.2529],
  ["Lynn", "MA", -70.9495, 42.4668], ["Fall River", "MA", -71.155, 41.7015],
  // Michigan
  ["Detroit", "MI", -83.0458, 42.3314], ["Grand Rapids", "MI", -85.6681, 42.9634],
  ["Warren", "MI", -83.0147, 42.4993], ["Sterling Heights", "MI", -83.0302, 42.5803],
  ["Lansing", "MI", -84.5555, 42.7325], ["Ann Arbor", "MI", -83.743, 42.2808],
  ["Flint", "MI", -83.6875, 43.0125], ["Dearborn", "MI", -83.1763, 42.3223],
  ["Kalamazoo", "MI", -85.5872, 42.2917], ["Battle Creek", "MI", -85.1797, 42.3212],
  ["Saginaw", "MI", -83.9508, 43.4195], ["Traverse City", "MI", -85.6206, 44.7631],
  ["Marquette", "MI", -87.3954, 46.5436], ["Muskegon", "MI", -86.2484, 43.2342],
  // Minnesota
  ["Minneapolis", "MN", -93.265, 44.9778], ["St. Paul", "MN", -93.09, 44.9537],
  ["Rochester", "MN", -92.4699, 44.0121], ["Duluth", "MN", -92.1005, 46.7867],
  ["Bloomington", "MN", -93.2983, 44.8408], ["Plymouth", "MN", -93.4555, 45.0105],
  ["Brooklyn Park", "MN", -93.3563, 45.0941], ["St. Cloud", "MN", -94.1632, 45.5579],
  ["Mankato", "MN", -94.0014, 44.1636], ["Maple Grove", "MN", -93.4558, 45.0724],
  // Mississippi
  ["Jackson", "MS", -90.1848, 32.2988], ["Gulfport", "MS", -89.0928, 30.3674],
  ["Southaven", "MS", -89.9787, 34.9889], ["Hattiesburg", "MS", -89.2903, 31.3271],
  ["Biloxi", "MS", -88.8853, 30.396], ["Meridian", "MS", -88.7037, 32.3643],
  ["Tupelo", "MS", -88.7034, 34.2576], ["Greenville", "MS", -91.0618, 33.4101],
  ["Vicksburg", "MS", -90.8779, 32.3526], ["Oxford", "MS", -89.5195, 34.3665],
  // Missouri
  ["Kansas City", "MO", -94.5786, 39.0997], ["St. Louis", "MO", -90.1994, 38.627],
  ["Springfield", "MO", -93.2923, 37.209], ["Columbia", "MO", -92.3341, 38.9517],
  ["Independence", "MO", -94.4155, 39.0911], ["Lee's Summit", "MO", -94.3826, 38.9108],
  ["O'Fallon", "MO", -90.6998, 38.8106], ["St. Joseph", "MO", -94.8463, 39.7687],
  ["Joplin", "MO", -94.5133, 37.0842], ["Jefferson City", "MO", -92.1735, 38.5768],
  // Montana
  ["Billings", "MT", -108.5007, 45.7833], ["Missoula", "MT", -114.0219, 46.8721],
  ["Great Falls", "MT", -111.3008, 47.5002], ["Bozeman", "MT", -111.0429, 45.677],
  ["Helena", "MT", -112.036, 46.5958], ["Kalispell", "MT", -114.3129, 48.192],
  // Nebraska
  ["Omaha", "NE", -95.9345, 41.2565], ["Lincoln", "NE", -96.7026, 40.8136],
  ["Bellevue", "NE", -95.8908, 41.1544], ["Grand Island", "NE", -98.342, 40.9264],
  ["Kearney", "NE", -99.0832, 40.6994], ["North Platte", "NE", -100.7601, 41.124],
  // Nevada
  ["Las Vegas", "NV", -115.1398, 36.1699], ["Henderson", "NV", -114.9817, 36.0395],
  ["Reno", "NV", -119.8138, 39.5296], ["North Las Vegas", "NV", -115.1175, 36.1989],
  ["Sparks", "NV", -119.7527, 39.5349], ["Carson City", "NV", -119.7674, 39.1638],
  // New Hampshire
  ["Manchester", "NH", -71.4548, 42.9956], ["Nashua", "NH", -71.4676, 42.7654],
  ["Concord", "NH", -71.5376, 43.2081], ["Dover", "NH", -70.8737, 43.1979],
  ["Rochester", "NH", -70.9756, 43.3045], ["Portsmouth", "NH", -70.7626, 43.0718],
  // New Jersey
  ["Newark", "NJ", -74.1724, 40.7357], ["Jersey City", "NJ", -74.0431, 40.7178],
  ["Paterson", "NJ", -74.1718, 40.9168], ["Elizabeth", "NJ", -74.2107, 40.664],
  ["Trenton", "NJ", -74.7429, 40.2171], ["Camden", "NJ", -75.1196, 39.9259],
  ["Atlantic City", "NJ", -74.4229, 39.3643], ["New Brunswick", "NJ", -74.4518, 40.4862],
  ["Princeton", "NJ", -74.6593, 40.3573], ["Hoboken", "NJ", -74.0324, 40.744],
  // New Mexico
  ["Albuquerque", "NM", -106.6504, 35.0844], ["Las Cruces", "NM", -106.746, 32.3199],
  ["Rio Rancho", "NM", -106.663, 35.2334], ["Santa Fe", "NM", -105.9378, 35.687],
  ["Roswell", "NM", -104.523, 33.3943], ["Farmington", "NM", -108.2187, 36.7281],
  // New York
  ["New York City", "NY", -74.006, 40.7128], ["New York", "NY", -74.006, 40.7128],
  ["NYC", "NY", -74.006, 40.7128], ["Manhattan", "NY", -73.9712, 40.7831],
  ["Brooklyn", "NY", -73.9442, 40.6782], ["Queens", "NY", -73.7949, 40.7282],
  ["Bronx", "NY", -73.8648, 40.8448], ["Staten Island", "NY", -74.1502, 40.5795],
  ["Buffalo", "NY", -78.8784, 42.8864], ["Rochester", "NY", -77.6109, 43.1566],
  ["Syracuse", "NY", -76.1474, 43.0481], ["Albany", "NY", -73.7562, 42.6526],
  ["Yonkers", "NY", -73.8988, 40.9312], ["Utica", "NY", -75.2327, 43.1009],
  ["Binghamton", "NY", -75.918, 42.0987], ["Ithaca", "NY", -76.4966, 42.444],
  ["White Plains", "NY", -73.7629, 41.034], ["Schenectady", "NY", -73.9399, 42.8143],
  // North Carolina
  ["Charlotte", "NC", -80.8431, 35.2271], ["Raleigh", "NC", -78.6382, 35.7796],
  ["Greensboro", "NC", -79.791, 36.0726], ["Durham", "NC", -78.8986, 35.994],
  ["Winston-Salem", "NC", -80.2442, 36.0999], ["Fayetteville", "NC", -78.8784, 35.0527],
  ["Cary", "NC", -78.7811, 35.7915], ["Wilmington", "NC", -77.9447, 34.2257],
  ["High Point", "NC", -80.0053, 35.9557], ["Asheville", "NC", -82.5515, 35.5951],
  ["Concord", "NC", -80.5795, 35.4088], ["Gastonia", "NC", -81.1871, 35.2621],
  ["Jacksonville", "NC", -77.43, 34.7541], ["Chapel Hill", "NC", -79.0558, 35.9132],
  ["Greenville", "NC", -77.3664, 35.6127],
  // North Dakota
  ["Fargo", "ND", -96.7898, 46.8772], ["Bismarck", "ND", -100.779, 46.8083],
  ["Grand Forks", "ND", -97.0329, 47.9253], ["Minot", "ND", -101.2923, 48.233],
  // Ohio
  ["Columbus", "OH", -82.9988, 39.9612], ["Cleveland", "OH", -81.6944, 41.4993],
  ["Cincinnati", "OH", -84.512, 39.1031], ["Toledo", "OH", -83.5552, 41.6528],
  ["Akron", "OH", -81.519, 41.0814], ["Dayton", "OH", -84.1916, 39.7589],
  ["Canton", "OH", -81.3784, 40.7989], ["Youngstown", "OH", -80.6495, 41.0998],
  ["Springfield", "OH", -83.8088, 39.9242], ["Hamilton", "OH", -84.5613, 39.3995],
  ["Mansfield", "OH", -82.5154, 40.7589], ["Lima", "OH", -84.1052, 40.7428],
  // Oklahoma
  ["Oklahoma City", "OK", -97.5164, 35.4676], ["Tulsa", "OK", -95.9928, 36.154],
  ["Norman", "OK", -97.4395, 35.2226], ["Broken Arrow", "OK", -95.7975, 36.0609],
  ["Lawton", "OK", -98.3959, 34.6036], ["Edmond", "OK", -97.4781, 35.6528],
  ["Moore", "OK", -97.4867, 35.3395], ["Enid", "OK", -97.8784, 36.3956],
  ["Stillwater", "OK", -97.0584, 36.1156], ["Muskogee", "OK", -95.3697, 35.7479],
  // Oregon
  ["Portland", "OR", -122.675, 45.5051], ["Eugene", "OR", -123.0868, 44.0521],
  ["Salem", "OR", -123.0351, 44.9429], ["Gresham", "OR", -122.431, 45.4983],
  ["Hillsboro", "OR", -122.99, 45.5229], ["Bend", "OR", -121.3153, 44.0582],
  ["Beaverton", "OR", -122.8037, 45.4871], ["Medford", "OR", -122.8756, 42.3265],
  ["Corvallis", "OR", -123.262, 44.5646], ["Albany", "OR", -123.1059, 44.6366],
  // Pennsylvania
  ["Philadelphia", "PA", -75.1652, 39.9526], ["Pittsburgh", "PA", -79.9959, 40.4406],
  ["Allentown", "PA", -75.4714, 40.6084], ["Reading", "PA", -75.9266, 40.3356],
  ["Erie", "PA", -80.0852, 42.1292], ["Scranton", "PA", -75.6624, 41.409],
  ["Bethlehem", "PA", -75.3785, 40.6259], ["Lancaster", "PA", -76.3055, 40.0379],
  ["Harrisburg", "PA", -76.8867, 40.2732], ["State College", "PA", -77.8599, 40.7934],
  ["Wilkes-Barre", "PA", -75.8913, 41.2459], ["York", "PA", -76.7277, 39.9626],
  // Rhode Island
  ["Providence", "RI", -71.4128, 41.824], ["Warwick", "RI", -71.4162, 41.7001],
  ["Cranston", "RI", -71.4372, 41.7798], ["Newport", "RI", -71.3128, 41.4901],
  // South Carolina
  ["Charleston", "SC", -79.9311, 32.7765], ["Columbia", "SC", -81.0348, 34.0007],
  ["North Charleston", "SC", -79.9748, 32.8546], ["Greenville", "SC", -82.394, 34.8526],
  ["Rock Hill", "SC", -81.0251, 34.9249], ["Spartanburg", "SC", -81.932, 34.9496],
  ["Mount Pleasant", "SC", -79.8623, 32.7941], ["Myrtle Beach", "SC", -78.8867, 33.6891],
  ["Hilton Head", "SC", -80.9345, 32.2163],
  // South Dakota
  ["Sioux Falls", "SD", -96.7311, 43.5446], ["Rapid City", "SD", -103.231, 44.0805],
  ["Aberdeen", "SD", -98.4864, 45.4647], ["Pierre", "SD", -100.351, 44.3683],
  // Tennessee
  ["Nashville", "TN", -86.7816, 36.1627], ["Memphis", "TN", -90.049, 35.1495],
  ["Knoxville", "TN", -83.9207, 35.9606], ["Chattanooga", "TN", -85.3097, 35.0456],
  ["Clarksville", "TN", -87.3595, 36.5298], ["Murfreesboro", "TN", -86.3903, 35.8456],
  ["Franklin", "TN", -86.8689, 35.9251], ["Jackson", "TN", -88.8143, 35.6145],
  ["Johnson City", "TN", -82.3534, 36.3134], ["Kingsport", "TN", -82.5618, 36.5484],
  // Texas
  ["Houston", "TX", -95.3698, 29.7604], ["Dallas", "TX", -96.797, 32.7767],
  ["Austin", "TX", -97.7431, 30.2672], ["San Antonio", "TX", -98.4936, 29.4241],
  ["Fort Worth", "TX", -97.3308, 32.7555], ["El Paso", "TX", -106.485, 31.7619],
  ["Arlington", "TX", -97.1081, 32.7357], ["Corpus Christi", "TX", -97.3964, 27.8006],
  ["Plano", "TX", -96.6989, 33.0198], ["Laredo", "TX", -99.5075, 27.5036],
  ["Lubbock", "TX", -101.8313, 33.5779], ["Irving", "TX", -96.9489, 32.814],
  ["Amarillo", "TX", -101.8313, 35.222], ["Grand Prairie", "TX", -96.9978, 32.746],
  ["McKinney", "TX", -96.6153, 33.1972], ["Frisco", "TX", -96.8236, 33.1507],
  ["Brownsville", "TX", -97.4975, 25.9017], ["Killeen", "TX", -97.7278, 31.1171],
  ["Pasadena", "TX", -95.2091, 29.6911], ["McAllen", "TX", -98.23, 26.2034],
  ["Midland", "TX", -102.0779, 31.9973], ["Odessa", "TX", -102.3676, 31.8457],
  ["Beaumont", "TX", -94.1018, 30.0802], ["Waco", "TX", -97.1464, 31.5493],
  ["Tyler", "TX", -95.3011, 32.3513], ["Round Rock", "TX", -97.6789, 30.5083],
  ["Abilene", "TX", -99.7331, 32.4487], ["Richardson", "TX", -96.7299, 32.9483],
  ["College Station", "TX", -96.3344, 30.628], ["Sugar Land", "TX", -95.6349, 29.6197],
  ["The Woodlands", "TX", -95.4891, 30.1588], ["Denton", "TX", -97.1331, 33.2148],
  ["Lewisville", "TX", -96.9942, 33.0462], ["Temple", "TX", -97.3428, 31.0982],
  ["Wichita Falls", "TX", -98.4934, 33.9137], ["San Marcos", "TX", -97.9414, 29.8833],
  // Utah
  ["Salt Lake City", "UT", -111.891, 40.7608], ["West Valley City", "UT", -111.9388, 40.6916],
  ["Provo", "UT", -111.6585, 40.2338], ["West Jordan", "UT", -111.9391, 40.6097],
  ["Orem", "UT", -111.6946, 40.2969], ["Sandy", "UT", -111.8338, 40.5651],
  ["Ogden", "UT", -111.9738, 41.223], ["St. George", "UT", -113.5684, 37.0965],
  ["Layton", "UT", -111.9711, 41.0602], ["Logan", "UT", -111.8338, 41.737],
  ["Lehi", "UT", -111.8507, 40.3916],
  // Vermont
  ["Burlington", "VT", -73.2126, 44.4759], ["Montpelier", "VT", -72.5754, 44.2601],
  ["Rutland", "VT", -72.9726, 43.6106],
  // Virginia
  ["Virginia Beach", "VA", -75.978, 36.8529], ["Norfolk", "VA", -76.2859, 36.8508],
  ["Chesapeake", "VA", -76.2875, 36.7682], ["Richmond", "VA", -77.436, 37.5407],
  ["Alexandria", "VA", -77.0469, 38.8048], ["Hampton", "VA", -76.3452, 37.0299],
  ["Roanoke", "VA", -79.9414, 37.271], ["Lynchburg", "VA", -79.1422, 37.4138],
  ["Charlottesville", "VA", -78.4767, 38.0293], ["Fredericksburg", "VA", -77.4605, 38.3032],
  ["Manassas", "VA", -77.4753, 38.7509], ["Newport News", "VA", -76.473, 37.0871],
  ["Suffolk", "VA", -76.5836, 36.7282], ["Danville", "VA", -79.395, 36.586],
  // Washington
  ["Seattle", "WA", -122.3321, 47.6062], ["Spokane", "WA", -117.426, 47.6588],
  ["Tacoma", "WA", -122.4443, 47.2529], ["Vancouver", "WA", -122.6615, 45.6387],
  ["Bellevue", "WA", -122.2015, 47.6101], ["Kent", "WA", -122.2348, 47.3809],
  ["Everett", "WA", -122.2021, 47.979], ["Renton", "WA", -122.2171, 47.4829],
  ["Spokane Valley", "WA", -117.3755, 47.651], ["Olympia", "WA", -122.9007, 47.0379],
  ["Bellingham", "WA", -122.4787, 48.7519], ["Kennewick", "WA", -119.2369, 46.2112],
  ["Yakima", "WA", -120.5059, 46.6021], ["Federal Way", "WA", -122.3126, 47.3223],
  ["Kirkland", "WA", -122.2087, 47.6815], ["Redmond", "WA", -122.1215, 47.674],
  // West Virginia
  ["Charleston", "WV", -81.6326, 38.3498], ["Huntington", "WV", -82.4452, 38.4192],
  ["Morgantown", "WV", -79.9559, 39.6295], ["Parkersburg", "WV", -81.5615, 39.2667],
  ["Wheeling", "WV", -80.7209, 40.064],
  // Wisconsin
  ["Milwaukee", "WI", -87.9065, 43.0389], ["Madison", "WI", -89.4012, 43.0731],
  ["Green Bay", "WI", -88.0198, 44.5133], ["Kenosha", "WI", -87.8212, 42.5847],
  ["Racine", "WI", -87.7845, 42.7261], ["Appleton", "WI", -88.415, 44.2619],
  ["Oshkosh", "WI", -88.5426, 44.0247], ["Eau Claire", "WI", -91.4985, 44.8113],
  ["Janesville", "WI", -89.0187, 42.6828], ["La Crosse", "WI", -91.2396, 43.8014],
  ["Sheboygan", "WI", -87.7145, 43.7508], ["Waukesha", "WI", -88.2317, 43.0117],
  // Wyoming
  ["Cheyenne", "WY", -104.8202, 41.14], ["Casper", "WY", -106.3131, 42.8666],
  ["Laramie", "WY", -105.5911, 41.3114], ["Gillette", "WY", -105.5022, 44.2911],
  // Washington D.C.
  ["Washington DC", "DC", -77.0369, 38.9072], ["Washington D.C.", "DC", -77.0369, 38.9072],
];

// Build lookup: plain city name (last entry wins for duplicates — largest city by convention)
// plus "City, ST" compound keys for all cities
const cityCoordinates: Record<string, [number, number]> = {};
for (const [city, st, lng, lat] of cityData) {
  cityCoordinates[city] = [lng, lat];
  cityCoordinates[`${city}, ${st}`] = [lng, lat];
  cityCoordinates[`${city} ${st}`] = [lng, lat];
}

function resolveToken(token: string, index: number): [number, number] | null {
  const trimmed = token.trim();
  const upper = trimmed.toUpperCase();
  const lower = trimmed.toLowerCase();

  // State abbreviation (e.g. "IL", "TX")
  const fullStateName = stateAbbreviations[upper];
  if (fullStateName && stateCoordinates[fullStateName]) {
    const c = stateCoordinates[fullStateName];
    const offset = (index % 5) * 0.5;
    return [c[0] + offset, c[1] + offset];
  }

  // City name
  const matchingCity = Object.keys(cityCoordinates).find(
    (city) => city.toLowerCase() === lower,
  );
  if (matchingCity) {
    const c = cityCoordinates[matchingCity];
    const offset = (index % 5) * 0.3;
    return [c[0] + offset, c[1] + offset];
  }

  // Full state / region name
  const matchingState = Object.keys(stateCoordinates).find(
    (key) => key.toLowerCase() === lower,
  );
  if (matchingState) {
    const c = stateCoordinates[matchingState];
    const offset = (index % 5) * 0.5;
    return [c[0] + offset, c[1] + offset];
  }

  return null;
}

function getCoordinates(dist: Distributor, index: number): [number, number] {
  if (dist.metadata?.longitude && dist.metadata?.latitude) {
    return [dist.metadata.longitude, dist.metadata.latitude];
  }
  if (dist.metadata?.lng && dist.metadata?.lat) {
    return [dist.metadata.lng, dist.metadata.lat];
  }

  if (dist.region) {
    // Try the full string first
    const full = resolveToken(dist.region, index);
    if (full) return full;

    // Parse "City, State" or "City, ST" compound formats
    const parts = dist.region.split(",").map((p) => p.trim()).filter(Boolean);
    if (parts.length >= 2) {
      // Try city part first (more precise), then state part as fallback
      for (const part of parts) {
        const result = resolveToken(part, index);
        if (result) return result;
      }
    }
  }

  const seed = dist.id
    .split("")
    .reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const lng = -120 + ((seed * 7 + index * 13) % 50);
  const lat = 30 + ((seed * 11 + index * 17) % 18);
  return [lng, lat];
}

type FilterType = "all" | "compliant" | "violations";

function buildGeoJSON(
  distributors: Distributor[],
  filter: FilterType,
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  const filtered = distributors.filter((d) => {
    if (filter === "all") return true;
    if (filter === "compliant") return !d.has_violation;
    if (filter === "violations") return d.has_violation;
    return true;
  });

  return {
    type: "FeatureCollection",
    features: filtered.map((d, idx) => {
      const coords = getCoordinates(d, idx);
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: coords },
        properties: {
          id: d.id,
          name: d.name,
          region: d.region || "Unknown",
          has_violation: d.has_violation ? 1 : 0,
          violation_count: d.violation_count ?? 0,
        },
      };
    }),
  };
}

const SOURCE_ID = "dealers";
const CLUSTER_LAYER = "dealer-clusters";
const CLUSTER_COUNT_LAYER = "dealer-cluster-count";
const UNCLUSTERED_GLOW = "dealer-unclustered-glow";
const UNCLUSTERED_LAYER = "dealer-unclustered";
const UNCLUSTERED_DOT = "dealer-unclustered-dot";

function DealerMap({ distributors }: DealerMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<any>(null);
  const [mapReady, setMapReady] = useState(false);
  const [filter, setFilter] = useState<FilterType>("all");

  // Initialize map via dynamic import to avoid SSR issues
  useEffect(() => {
    if (!mapContainer.current || mapInstanceRef.current) return;

    let cancelled = false;

    (async () => {
      const mapboxgl = (await import("mapbox-gl")).default;
      mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

      if (cancelled || !mapContainer.current) return;

      const map = new mapboxgl.Map({
        container: mapContainer.current,
        style: "mapbox://styles/mapbox/dark-v11",
        center: [-96, 38],
        zoom: 3.5,
        attributionControl: false,
        pitchWithRotate: false,
      });

      map.addControl(
        new mapboxgl.NavigationControl({ showCompass: false }),
        "top-right",
      );

      map.on("load", () => {
        if (cancelled) return;

        map.resize();

        map.addSource(SOURCE_ID, {
          type: "geojson",
          data: buildGeoJSON(distributors, filter),
          cluster: true,
          clusterMaxZoom: 12,
          clusterRadius: 50,
          clusterProperties: {
            violationSum: ["+", ["get", "has_violation"]],
          },
        });

        map.addLayer({
          id: CLUSTER_LAYER,
          type: "circle",
          source: SOURCE_ID,
          filter: ["has", "point_count"],
          paint: {
            "circle-color": [
              "case",
              [">", ["get", "violationSum"], 0],
              "#f97316",
              "#22c55e",
            ],
            "circle-radius": [
              "step",
              ["get", "point_count"],
              18, 5, 24, 15, 32, 30, 40,
            ],
            "circle-stroke-width": 2,
            "circle-stroke-color": "rgba(255,255,255,0.15)",
            "circle-opacity": 0.85,
          },
        });

        map.addLayer({
          id: CLUSTER_COUNT_LAYER,
          type: "symbol",
          source: SOURCE_ID,
          filter: ["has", "point_count"],
          layout: {
            "text-field": "{point_count_abbreviated}",
            "text-font": ["DIN Pro Medium", "Arial Unicode MS Bold"],
            "text-size": 13,
          },
          paint: { "text-color": "#ffffff" },
        });

        map.addLayer({
          id: UNCLUSTERED_GLOW,
          type: "circle",
          source: SOURCE_ID,
          filter: [
            "all",
            ["!", ["has", "point_count"]],
            ["==", ["get", "has_violation"], 1],
          ],
          paint: {
            "circle-radius": 14,
            "circle-color": "rgba(239, 68, 68, 0.25)",
            "circle-blur": 0.6,
          },
        });

        map.addLayer({
          id: UNCLUSTERED_LAYER,
          type: "circle",
          source: SOURCE_ID,
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": 7,
            "circle-color": [
              "case",
              ["==", ["get", "has_violation"], 1],
              "#ef4444",
              "#22c55e",
            ],
            "circle-stroke-width": 2,
            "circle-stroke-color": [
              "case",
              ["==", ["get", "has_violation"], 1],
              "#fca5a5",
              "#86efac",
            ],
          },
        });

        map.addLayer({
          id: UNCLUSTERED_DOT,
          type: "circle",
          source: SOURCE_ID,
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": 2.5,
            "circle-color": [
              "case",
              ["==", ["get", "has_violation"], 1],
              "#fecaca",
              "#bbf7d0",
            ],
          },
        });

        setMapReady(true);
      });

      map.on("click", CLUSTER_LAYER, (e) => {
        const features = map.queryRenderedFeatures(e.point, {
          layers: [CLUSTER_LAYER],
        });
        if (!features.length) return;
        const clusterId = features[0].properties?.cluster_id;
        const source = map.getSource(SOURCE_ID) as any;
        source.getClusterExpansionZoom(clusterId, (err: any, zoom: number) => {
          if (err || zoom == null) return;
          const geometry = features[0].geometry as GeoJSON.Point;
          map.easeTo({
            center: geometry.coordinates as [number, number],
            zoom,
          });
        });
      });

      let popup: mapboxgl.Popup | null = null;

      map.on("mouseenter", UNCLUSTERED_LAYER, (e) => {
        map.getCanvas().style.cursor = "pointer";
        if (!e.features?.length) return;
        const f = e.features[0];
        const coords = (f.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        const { name, region, has_violation, violation_count } =
          f.properties as Record<string, unknown>;

        const isViolator = has_violation === 1 || has_violation === "1";
        const statusHtml = isViolator
          ? `<span style="color:#f87171">⚠ Issues Detected (${violation_count})</span>`
          : `<span style="color:#4ade80">✓ Compliant</span>`;

        popup?.remove();
        popup = new mapboxgl.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 12,
          className: "dealer-map-popup",
        })
          .setLngLat(coords)
          .setHTML(
            `<div style="font-family:system-ui,sans-serif;font-size:12px;line-height:1.4">
              <div style="font-weight:600;color:#f1f5f9">${name}</div>
              <div style="color:#94a3b8">${region}</div>
              <div style="margin-top:2px">${statusHtml}</div>
            </div>`,
          )
          .addTo(map);
      });

      map.on("mouseleave", UNCLUSTERED_LAYER, () => {
        map.getCanvas().style.cursor = "";
        popup?.remove();
        popup = null;
      });

      map.on("mouseenter", CLUSTER_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", CLUSTER_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });

      mapInstanceRef.current = map;
    })();

    return () => {
      cancelled = true;
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update source data when distributors or filter change
  useEffect(() => {
    if (!mapReady || !mapInstanceRef.current) return;
    const source = mapInstanceRef.current.getSource(SOURCE_ID);
    if (source) {
      source.setData(buildGeoJSON(distributors, filter));
    }
  }, [distributors, filter, mapReady]);

  const compliantCount = distributors.filter((d) => !d.has_violation).length;
  const violationCount = distributors.filter((d) => d.has_violation).length;

  return (
    <div style={{ height: 400, width: "100%", position: "relative" }}>
      <div
        ref={mapContainer}
        style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%" }}
      />

      {/* Legend filter controls */}
      <div
        className="absolute bottom-0 left-0 flex items-center gap-2 text-xs bg-background/90 backdrop-blur-sm px-3 py-2 rounded-tr border-t border-r border-border z-20"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={() =>
            setFilter(filter === "compliant" ? "all" : "compliant")
          }
          className={`flex items-center gap-1.5 px-2 py-1 rounded transition-all cursor-pointer ${
            filter === "compliant"
              ? "bg-green-500/20 ring-1 ring-green-500"
              : "hover:bg-secondary/50"
          }`}
        >
          <div className="w-3 h-3 rounded-full bg-green-500 border border-green-300" />
          <span
            className={
              filter === "compliant"
                ? "text-green-400"
                : "text-muted-foreground"
            }
          >
            Compliant ({compliantCount})
          </span>
        </button>
        <button
          type="button"
          onClick={() =>
            setFilter(filter === "violations" ? "all" : "violations")
          }
          className={`flex items-center gap-1.5 px-2 py-1 rounded transition-all cursor-pointer ${
            filter === "violations"
              ? "bg-red-500/20 ring-1 ring-red-500"
              : "hover:bg-secondary/50"
          }`}
        >
          <div className="w-3 h-3 rounded-full bg-red-500 border border-red-300" />
          <span
            className={
              filter === "violations"
                ? "text-red-400"
                : "text-muted-foreground"
            }
          >
            Violations ({violationCount})
          </span>
        </button>
        {filter !== "all" && (
          <button
            type="button"
            onClick={() => setFilter("all")}
            className="ml-1 px-2 py-1 text-muted-foreground hover:text-foreground hover:bg-secondary/50 rounded transition-all cursor-pointer"
          >
            Show All
          </button>
        )}
      </div>

      {/* Empty state */}
      {distributors.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm z-20 pointer-events-none">
          No distributors to display
        </div>
      )}
    </div>
  );
}

export default memo(DealerMap);
