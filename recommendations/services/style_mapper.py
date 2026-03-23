"""
Style and country mapping utilities for beer recommendations.
"""

STYLE_CATEGORY_MAP = {
    # IPAs
    'IPA': 'IPA', 'DIPA': 'IPA', 'Imperial IPA': 'IPA', 'Double IPA': 'IPA',
    'Triple IPA': 'IPA', 'New England': 'IPA', 'Hazy': 'IPA', 'NEIPA': 'IPA',
    'Session IPA': 'IPA', 'Black IPA': 'IPA', 'White IPA': 'IPA', 'Brut IPA': 'IPA',
    'Milkshake IPA': 'IPA', 'Cold IPA': 'IPA',
    
    # Stouts
    'Stout': 'Stout', 'Imperial Stout': 'Stout', 'Pastry Stout': 'Stout',
    'Milk Stout': 'Stout', 'Oatmeal Stout': 'Stout', 'Coffee Stout': 'Stout',
    'Chocolate Stout': 'Stout', 'Foreign Stout': 'Stout', 'American Stout': 'Stout',
    'Russian Imperial': 'Stout',
    
    # Porters
    'Porter': 'Porter', 'Baltic Porter': 'Porter', 'Imperial Porter': 'Porter',
    
    # Sours
    'Sour': 'Sour', 'Fruited Sour': 'Sour', 'Gose': 'Sour', 'Berliner Weisse': 'Sour',
    'Kettle Sour': 'Sour', 'Smoothie': 'Sour', 'Pastry Sour': 'Sour',
    
    # Wild / Lambic
    'Wild Ale': 'Wild/Lambic', 'Lambic': 'Wild/Lambic', 'Lambiek': 'Wild/Lambic',
    'Gueuze': 'Wild/Lambic', 'Geuze': 'Wild/Lambic', 'Kriek': 'Wild/Lambic',
    'Framboise': 'Wild/Lambic', 'Faro': 'Wild/Lambic', 'Fruit Lambic': 'Wild/Lambic',
    'Flanders Red': 'Wild/Lambic', 'Flanders Oud Bruin': 'Wild/Lambic', 'Oud Bruin': 'Wild/Lambic',
    
    # Belgian
    'Tripel': 'Belgian', 'Dubbel': 'Belgian', 'Quadrupel': 'Belgian', 'Quad': 'Belgian',
    'Belgian Strong': 'Belgian', 'Belgian Dark': 'Belgian', 'Belgian Golden': 'Belgian',
    'Belgian Blonde': 'Belgian', 'Belgian Pale': 'Belgian', 'Abbey': 'Belgian',
    'Trappist': 'Belgian', 'Saison': 'Belgian', 'Farmhouse': 'Belgian',
    
    # Wheat
    'Witbier': 'Wheat', 'Wheat': 'Wheat', 'Hefeweizen': 'Wheat', 'Weissbier': 'Wheat',
    'Weizen': 'Wheat', 'Dunkelweizen': 'Wheat',
    
    # Lagers
    'Lager': 'Lager', 'Pilsner': 'Lager', 'Pilsener': 'Lager', 'Pils': 'Lager',
    'Helles': 'Lager', 'Kellerbier': 'Lager', 'Vienna Lager': 'Lager', 'IPL': 'Lager',
    
    # Bock
    'Bock': 'Bock', 'Doppelbock': 'Bock', 'Eisbock': 'Bock', 'Maibock': 'Bock',
    
    # Pale Ales
    'Pale Ale': 'Pale Ale', 'American Pale Ale': 'Pale Ale', 'APA': 'Pale Ale',
    
    # Barleywine
    'Barleywine': 'Barleywine', 'Barley Wine': 'Barleywine',
    
    # German
    'Kolsch': 'German', 'Altbier': 'German', 'Schwarzbier': 'German',
    'Marzen': 'German', 'Oktoberfest': 'German', 'Rauchbier': 'German',
    
    # British
    'Bitter': 'British', 'ESB': 'British', 'Brown Ale': 'British', 'Old Ale': 'British',
    
    # Low/No Alcohol
    'Non-Alcoholic': 'Low/No Alcohol', 'Alcoholvrij': 'Low/No Alcohol', '0.0%': 'Low/No Alcohol',
}

COUNTRY_REGION_MAP = {
    'Belgium': 'Western Europe', 'Netherlands': 'Western Europe', 'Germany': 'Western Europe',
    'France': 'Western Europe', 'Austria': 'Western Europe',
    'United Kingdom': 'UK & Ireland', 'UK': 'UK & Ireland', 'England': 'UK & Ireland',
    'Scotland': 'UK & Ireland', 'Ireland': 'UK & Ireland',
    'Denmark': 'Scandinavia', 'Sweden': 'Scandinavia', 'Norway': 'Scandinavia',
    'Finland': 'Scandinavia', 'Iceland': 'Scandinavia',
    'Czech Republic': 'Eastern Europe', 'Poland': 'Eastern Europe', 'Estonia': 'Eastern Europe',
    'Italy': 'Southern Europe', 'Spain': 'Southern Europe', 'Portugal': 'Southern Europe',
    'United States': 'North America', 'USA': 'North America', 'Canada': 'North America',
    'Australia': 'Pacific', 'New Zealand': 'Pacific',
    'Japan': 'Asia',
}


def get_style_category(soort_bier: str = None, untappd_style: str = None) -> str:
    if soort_bier:
        soort_lower = soort_bier.lower()
        for key, category in STYLE_CATEGORY_MAP.items():
            if key.lower() in soort_lower:
                return category
    if untappd_style:
        style_lower = untappd_style.lower()
        for key, category in STYLE_CATEGORY_MAP.items():
            if key.lower() in style_lower:
                return category
        first_part = untappd_style.split(' - ')[0].strip()
        if first_part:
            return first_part
    if soort_bier:
        return soort_bier
    return 'Unknown'


def get_country_region(country: str) -> str:
    if not country:
        return 'Unknown'
    if country in COUNTRY_REGION_MAP:
        return COUNTRY_REGION_MAP[country]
    country_lower = country.lower()
    for key, region in COUNTRY_REGION_MAP.items():
        if key.lower() == country_lower:
            return region
    return 'Other'


def get_all_style_categories() -> list:
    return sorted(set(STYLE_CATEGORY_MAP.values()))


def get_all_country_regions() -> list:
    return sorted(set(COUNTRY_REGION_MAP.values()))
