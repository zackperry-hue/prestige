"""Sport type normalization mappings across platforms."""

# Whoop sport_id → normalized type
WHOOP_SPORT_MAP: dict[int, str] = {
    -1: "activity",
    0: "running",
    1: "cycling",
    2: "strength",
    3: "rowing",
    4: "yoga",
    5: "swimming",
    6: "hiit",
    7: "walking",
    8: "hiking",
    9: "crossfit",
    10: "tennis",
    11: "boxing",
    12: "basketball",
    13: "soccer",
    14: "martial_arts",
    15: "dance",
    16: "golf",
    17: "pilates",
    18: "surfing",
    19: "climbing",
    20: "skiing",
    21: "snowboarding",
    22: "functional_fitness",
    23: "duathlon",
    24: "triathlon",
    25: "motocross",
    26: "rugby",
    27: "cricket",
    28: "volleyball",
    29: "lacrosse",
    30: "ice_hockey",
    31: "field_hockey",
    32: "softball",
    33: "baseball",
    34: "track_and_field",
    35: "squash",
    36: "badminton",
    37: "table_tennis",
    38: "sailing",
    39: "kayaking",
    40: "water_polo",
    41: "football",
    42: "horse_riding",
    43: "meditation",
    44: "spin",
    45: "elliptical",
    46: "stairmaster",
    47: "stretching",
    48: "diving",
    49: "skateboarding",
    50: "wheelchair_pushing",
    51: "other",
    63: "obstacle_course_racing",
    64: "pickleball",
}

# Strava activity type → normalized type
STRAVA_SPORT_MAP: dict[str, str] = {
    "Run": "running",
    "Ride": "cycling",
    "Swim": "swimming",
    "Walk": "walking",
    "Hike": "hiking",
    "WeightTraining": "strength",
    "Workout": "other",
    "Yoga": "yoga",
    "CrossFit": "crossfit",
    "Rowing": "rowing",
    "Elliptical": "elliptical",
    "StairStepper": "stairmaster",
    "Kayaking": "kayaking",
    "Surfing": "surfing",
    "RockClimbing": "climbing",
    "AlpineSki": "skiing",
    "Snowboard": "snowboarding",
    "Golf": "golf",
    "Soccer": "soccer",
    "Tennis": "tennis",
    "Skateboard": "skateboarding",
    "NordicSki": "skiing",
    "IceSkate": "ice_skating",
    "Badminton": "badminton",
    "Squash": "squash",
    "TableTennis": "table_tennis",
    "Pickleball": "pickleball",
    "VirtualRide": "cycling",
    "VirtualRun": "running",
    "TrailRun": "running",
    "MountainBikeRide": "cycling",
    "GravelRide": "cycling",
    "EBikeRide": "cycling",
    "Velodrome": "cycling",
    "Sail": "sailing",
    "Canoeing": "kayaking",
    "Handcycle": "cycling",
    "Wheelchair": "wheelchair_pushing",
    "Pilates": "pilates",
    "HIIT": "hiit",
}

# Wahoo workout_type_id → normalized type (from Wahoo Cloud API docs)
WAHOO_SPORT_MAP: dict[int, str] = {
    0: "cycling",           # Biking
    1: "running",           # Running
    2: "other",             # Fitness Equipment
    3: "running",           # Running Track
    4: "running",           # Trail Running
    5: "running",           # Treadmill Running
    6: "walking",           # Walking
    7: "walking",           # Speed Walking
    8: "walking",           # Nordic Walking
    9: "hiking",            # Hiking
    10: "hiking",           # Mountaineering
    11: "cycling",          # Cyclocross
    12: "cycling",          # Indoor Cycling
    13: "cycling",          # Mountain Biking
    14: "cycling",          # Recumbent Biking
    15: "cycling",          # Road Biking
    16: "cycling",          # Track Cycling
    17: "other",            # Motocycling
    18: "other",            # General Fitness Equipment
    19: "running",          # Treadmill
    20: "elliptical",       # Elliptical
    21: "cycling",          # Stationary Bike
    22: "rowing",           # Rowing Machine
    23: "stairmaster",      # Stair Climber
    25: "swimming",         # Lap Swimming
    26: "swimming",         # Open Water Swimming
    27: "snowboarding",     # Snowboarding
    28: "skiing",           # Skiing
    29: "skiing",           # Downhill Skiing
    30: "skiing",           # Cross-Country Skiing
    31: "other",            # Skating
    32: "other",            # Ice Skating
    33: "other",            # Inline Skating
    34: "other",            # Longboarding
    35: "sailing",          # Sailing
    36: "surfing",          # Windsurfing
    37: "kayaking",         # Canoeing
    38: "kayaking",         # Kayaking
    39: "rowing",           # Rowing
    40: "surfing",          # Kiteboarding
    41: "other",            # Stand-Up Paddleboarding
    42: "other",            # Workout
    43: "other",            # Cardio Class
    44: "stairmaster",      # Stair Climber
    45: "other",            # Wheelchair
    46: "golf",             # Golfing
    47: "other",            # Other
    49: "cycling",          # Indoor Cycling Class
    56: "walking",          # Treadmill Walking
    61: "cycling",          # Indoor Trainer
    62: "triathlon",        # Multisport
    63: "other",            # Transition
    64: "cycling",          # E-Biking
    65: "other",            # Tickr Offline
    66: "yoga",             # Yoga
    67: "running",          # Running Race
    68: "cycling",          # Indoor Virtual Cycling
    69: "meditation",       # Mental Strength
    70: "cycling",          # Handcycling
    71: "running",          # Indoor Virtual Running
    255: "other",           # Unknown
}


# Garmin activityType.typeKey → normalized type
GARMIN_SPORT_MAP: dict[str, str] = {
    "running": "running",
    "trail_running": "running",
    "treadmill_running": "running",
    "track_running": "running",
    "cycling": "cycling",
    "road_biking": "cycling",
    "mountain_biking": "cycling",
    "gravel_cycling": "cycling",
    "indoor_cycling": "cycling",
    "virtual_ride": "cycling",
    "swimming": "swimming",
    "lap_swimming": "swimming",
    "open_water_swimming": "swimming",
    "walking": "walking",
    "hiking": "hiking",
    "strength_training": "strength",
    "yoga": "yoga",
    "pilates": "pilates",
    "elliptical": "elliptical",
    "stair_climbing": "stairmaster",
    "rowing": "rowing",
    "indoor_rowing": "rowing",
    "kayaking": "kayaking",
    "surfing": "surfing",
    "rock_climbing": "climbing",
    "bouldering": "climbing",
    "skiing": "skiing",
    "resort_skiing": "skiing",
    "cross_country_skiing": "skiing",
    "snowboarding": "snowboarding",
    "golf": "golf",
    "tennis": "tennis",
    "pickleball": "pickleball",
    "badminton": "badminton",
    "table_tennis": "table_tennis",
    "soccer": "soccer",
    "basketball": "basketball",
    "volleyball": "volleyball",
    "baseball": "baseball",
    "softball": "softball",
    "football": "football",
    "rugby": "rugby",
    "ice_hockey": "ice_hockey",
    "field_hockey": "field_hockey",
    "lacrosse": "lacrosse",
    "boxing": "boxing",
    "martial_arts": "martial_arts",
    "hiit": "hiit",
    "crossfit": "crossfit",
    "dance": "dance",
    "meditation": "meditation",
    "breathwork": "meditation",
    "stretching": "stretching",
    "skateboarding": "skateboarding",
    "sailing": "sailing",
    "triathlon": "triathlon",
    "duathlon": "duathlon",
    "multi_sport": "other",
    "other": "other",
}


def normalize_sport_type(platform: str, raw_type: int | str) -> str:
    if platform == "whoop":
        return WHOOP_SPORT_MAP.get(int(raw_type), "other")
    elif platform == "strava":
        return STRAVA_SPORT_MAP.get(str(raw_type), "other")
    elif platform == "wahoo":
        return WAHOO_SPORT_MAP.get(int(raw_type), "other")
    elif platform == "garmin":
        return GARMIN_SPORT_MAP.get(str(raw_type).lower(), "other")
    return "other"
