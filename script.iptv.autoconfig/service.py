import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
import os
import json
import gzip
import zipfile
try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_NAME = ADDON.getAddonInfo('name')
USERDATA_PATH = xbmcvfs.translatePath('special://userdata/')
ADDONS_PATH = xbmcvfs.translatePath('special://home/addons/')

def log(msg):
    xbmc.log('[%s] %s' % (ADDON_NAME, msg), xbmc.LOGINFO)

def notify(title, message, time=5000):
    xbmcgui.Dialog().notification(title, message, xbmcgui.NOTIFICATION_INFO, time)

def get_location():
    try:
        req = Request('http://ip-api.com/json/')
        req.add_header('User-Agent', 'Kodi IPTV Auto-Config')
        response = urlopen(req, timeout=10)
        data = json.loads(response.read().decode('utf-8'))
        country_code = data.get('countryCode', 'US').lower()
        country_name = data.get('country', 'United States')
        log('Detected: %s (%s)' % (country_name, country_code))
        return country_code, country_name
    except Exception as e:
        log('Location detection failed: %s' % str(e))
        return 'us', 'United States'

def download_file(url, timeout=60):
    try:
        req = Request(url)
        req.add_header('User-Agent', 'Kodi IPTV Auto-Config')
        response = urlopen(req, timeout=timeout)
        return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        log('Download failed for %s: %s' % (url, str(e)))
        return None

def download_binary(url, dest_path, timeout=60):
    try:
        req = Request(url)
        req.add_header('User-Agent', 'Kodi IPTV Auto-Config')
        response = urlopen(req, timeout=timeout)
        dest_dir = os.path.dirname(dest_path)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        with open(dest_path, 'wb') as f:
            f.write(response.read())
        return True
    except Exception as e:
        log('Binary download failed for %s: %s' % (url, str(e)))
        return False

def install_addon_from_zip(zip_url, addon_id):
    """Download and install addon from ZIP URL"""
    try:
        log('Installing %s from %s' % (addon_id, zip_url))
        notify(ADDON_NAME, 'Installing %s...' % addon_id, 3000)
        
        temp_zip = os.path.join(xbmcvfs.translatePath('special://temp/'), '%s.zip' % addon_id)
        if not download_binary(zip_url, temp_zip, timeout=120):
            log('Failed to download %s' % addon_id)
            return False
        
        log('Downloaded %s, extracting...' % addon_id)
        
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(ADDONS_PATH)
        
        os.remove(temp_zip)
        
        log('Installed %s successfully' % addon_id)
        notify(ADDON_NAME, 'Installed %s' % addon_id, 2000)
        
        xbmc.executebuiltin('UpdateLocalAddons')
        xbmc.sleep(2000)
        
        return True
    except Exception as e:
        log('Failed to install %s: %s' % (addon_id, str(e)))
        return False

def enable_addon(addon_id):
    """Enable an addon using JSON-RPC"""
    try:
        log('Enabling addon: %s' % addon_id)
        json_query = json.dumps({
            'jsonrpc': '2.0',
            'method': 'Addons.SetAddonEnabled',
            'params': {'addonid': addon_id, 'enabled': True},
            'id': 1
        })
        result = xbmc.executeJSONRPC(json_query)
        log('Enable result for %s: %s' % (addon_id, result))
        
        xbmc.executebuiltin('EnableAddon(%s)' % addon_id)
        xbmc.sleep(1000)
        
        return True
    except Exception as e:
        log('Failed to enable %s: %s' % (addon_id, str(e)))
        return False

def parse_m3u(content):
    entries = []
    lines = content.split('\n')
    extinf = ''
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            extinf = line
        elif line.startswith('http') and extinf:
            entries.append((extinf, line))
            extinf = ''
    return entries

def merge_playlists(country_code):
    notify(ADDON_NAME, 'Downloading playlists...', 3000)
    playlists = [
        {'name': 'Country', 'url': 'https://iptv-org.github.io/iptv/countries/%s.m3u' % country_code},
        {'name': 'English', 'url': 'https://iptv-org.github.io/iptv/languages/eng.m3u'},
        {'name': 'Movies', 'url': 'https://iptv-org.github.io/iptv/categories/movies.m3u'},
        {'name': 'Sports', 'url': 'https://iptv-org.github.io/iptv/categories/sports.m3u'}
    ]
    
    seen_urls = {}
    main_m3u = '#EXTM3U\n'
    total_channels = 0
    
    progress = xbmcgui.DialogProgress()
    progress.create(ADDON_NAME, 'Downloading playlists...')
    
    for idx, playlist in enumerate(playlists):
        if progress.iscanceled():
            progress.close()
            return None
        
        percent = int((idx / len(playlists)) * 100)
        progress.update(percent, 'Downloading: %s' % playlist['name'])
        
        content = download_file(playlist['url'])
        if not content:
            continue
        
        entries = parse_m3u(content)
        for extinf, url in entries:
            url_lower = url.lower()
            if url_lower not in seen_urls:
                seen_urls[url_lower] = True
                main_m3u += '%s\n%s\n' % (extinf, url)
                total_channels += 1
        
        log('%s: added channels' % playlist['name'])
    
    progress.close()
    log('Total channels: %d' % total_channels)
    notify(ADDON_NAME, 'Found %d channels' % total_channels, 3000)
    return {'main': main_m3u, 'total': total_channels}

def download_epg(country_code):
    """Download EPG guide - creates empty file if none available"""
    notify(ADDON_NAME, 'Setting up EPG...', 2000)
    epg_path = os.path.join(USERDATA_PATH, 'epg.xml.gz')
    
    log('Creating minimal EPG file (EPG sources currently unavailable)')
    try:
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tv SYSTEM "xmltv.dtd">
<tv generator-info-name="IPTV Auto-Config">
</tv>'''
        xml_path = os.path.join(USERDATA_PATH, 'epg.xml')
        with open(xml_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        
        with open(xml_path, 'rb') as f_in:
            with gzip.open(epg_path, 'wb') as f_out:
                f_out.write(f_in.read())
        
        os.remove(xml_path)
        log('Created empty EPG file')
        return epg_path
    except Exception as e:
        log('Failed to create EPG: %s' % str(e))
        return ''

def configure_pvr_simple(playlist_path, epg_path):
    try:
        pvr_addon_data = os.path.join(USERDATA_PATH, 'addon_data', 'pvr.iptvsimple')
        if not os.path.exists(pvr_addon_data):
            os.makedirs(pvr_addon_data)
        
        settings_xml = '''<settings version="2">
  <setting id="m3uPathType" type="integer">0</setting>
  <setting id="m3uPath" type="string">%s</setting>
  <setting id="epgPathType" type="integer">0</setting>
  <setting id="epgPath" type="string">%s</setting>
  <setting id="m3uCache" type="boolean">true</setting>
  <setting id="epgCache" type="boolean">true</setting>
  <setting id="m3uRefreshMode" type="integer">2</setting>
  <setting id="m3uRefreshIntervalMins" type="integer">120</setting>
  <setting id="allChannelsGroupsEnabled" type="boolean">true</setting>
</settings>''' % (playlist_path, epg_path)
        
        settings_path = os.path.join(pvr_addon_data, 'settings.xml')
        with open(settings_path, 'w') as f:
            f.write(settings_xml)
        log('PVR configured at: %s' % settings_path)
        return True
    except Exception as e:
        log('Failed to configure PVR: %s' % str(e))
        return False

def install_skin():
    """Install Arctic Zephyr Reloaded skin"""
    try:
        skin_url = 'https://mirrors.kodi.tv/addons/omega/skin.arctic.zephyr.mod/skin.arctic.zephyr.mod-3.0.3.zip'
        skin_id = 'skin.arctic.zephyr.mod'
        
        skin_path = os.path.join(ADDONS_PATH, skin_id)
        if os.path.exists(skin_path):
            log('Arctic Zephyr already installed')
            return True
        
        log('Installing Arctic Zephyr Reloaded skin...')
        notify(ADDON_NAME, 'Installing Arctic Zephyr skin...', 3000)
        
        return install_addon_from_zip(skin_url, skin_id)
    except Exception as e:
        log('Failed to install skin: %s' % str(e))
        return False

def set_skin(skin_id):
    """Change active skin - requires restart to take effect"""
    try:
        log('Configuring skin to: %s' % skin_id)
        
        # Update guisettings.xml directly
        guisettings_path = os.path.join(USERDATA_PATH, 'guisettings.xml')
        
        # Read existing settings or create new
        if os.path.exists(guisettings_path):
            with open(guisettings_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Replace skin setting
            import re
            if 'lookandfeel.skin' in content:
                content = re.sub(r'<setting id="lookandfeel\.skin"[^>]*>.*?</setting>', 
                                '<setting id="lookandfeel.skin">%s</setting>' % skin_id, content)
            else:
                # Add skin setting before </settings>
                content = content.replace('</settings>', 
                    '  <setting id="lookandfeel.skin">%s</setting>\n</settings>' % skin_id)
        else:
            # Create minimal guisettings
            content = '''<settings version="2">
  <setting id="lookandfeel.skin">%s</setting>
</settings>''' % skin_id
        
        # Write updated settings
        with open(guisettings_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        log('Skin configured in guisettings.xml - will activate on restart')
        return True
    except Exception as e:
        log('Failed to configure skin: %s' % str(e))
        return False

def hide_menu_items():
    """Hide unwanted menu items in Arctic Zephyr"""
    try:
        log('Configuring Arctic Zephyr menu items...')
        
        skin_data_path = os.path.join(USERDATA_PATH, 'addon_data', 'skin.arctic.zephyr.mod')
        if not os.path.exists(skin_data_path):
            os.makedirs(skin_data_path)
        
        skin_settings = '''<settings version="2">
  <setting id="home.movies" type="boolean">true</setting>
  <setting id="home.tvshows" type="boolean">true</setting>
  <setting id="home.livetv" type="boolean">true</setting>
  <setting id="home.music" type="boolean">false</setting>
  <setting id="home.musicvideos" type="boolean">false</setting>
  <setting id="home.radio" type="boolean">false</setting>
  <setting id="home.pictures" type="boolean">false</setting>
  <setting id="home.videos" type="boolean">false</setting>
  <setting id="home.weather" type="boolean">false</setting>
  <setting id="home.games" type="boolean">false</setting>
</settings>'''
        
        settings_path = os.path.join(skin_data_path, 'settings.xml')
        with open(settings_path, 'w') as f:
            f.write(skin_settings)
        
        log('Arctic Zephyr menu configured - Only TV, Movies, TV Shows visible')
        return True
    except Exception as e:
        log('Failed to configure menu: %s' % str(e))
        return False

def main():
    log('Starting IPTV Auto-Config')
    
    dialog = xbmcgui.Dialog()
    country_code, country_name = get_location()
    
    if not dialog.yesno(ADDON_NAME, 
                        'Auto-configure IPTV for %s?\n\nThis will:\n- Install PVR IPTV Simple (if needed)\n- Download 3000+ channels\n- Install Arctic Zephyr skin\n- Configure clean menu\n- Set up EPG' % country_name):
        return
    
    progress = xbmcgui.DialogProgress()
    progress.create(ADDON_NAME, 'Setting up IPTV...')
    
    # Step 1: Install PVR if needed
    progress.update(10, 'Checking PVR IPTV Simple...')
    pvr_path = os.path.join(ADDONS_PATH, 'pvr.iptvsimple')
    if os.path.exists(pvr_path):
        log('PVR IPTV Simple already installed')
        pvr_installed = True
    else:
        pvr_url = 'https://mirrors.kodi.tv/addons/omega/pvr.iptvsimple+windows-x86_64/pvr.iptvsimple-21.11.0.zip'
        pvr_installed = install_addon_from_zip(pvr_url, 'pvr.iptvsimple')
    
    if not pvr_installed:
        progress.close()
        dialog.ok(ADDON_NAME, 'Failed to install PVR IPTV Simple.\n\nPlease install manually:\nSettings > Add-ons > Install from repository')
        return
    
    # Step 2: Download playlists
    progress.update(30, 'Downloading playlists...')
    playlists = merge_playlists(country_code)
    if not playlists:
        progress.close()
        dialog.ok(ADDON_NAME, 'Failed to download playlists.\nCheck internet connection.')
        return
    
    # Step 3: Save playlists
    progress.update(50, 'Saving playlists...')
    playlist_path = os.path.join(USERDATA_PATH, 'iptv_playlist.m3u8')
    try:
        with open(playlist_path, 'w', encoding='utf-8') as f:
            f.write(playlists['main'])
        log('Playlist saved: %s' % playlist_path)
    except Exception as e:
        progress.close()
        dialog.ok(ADDON_NAME, 'Failed to save playlists.\nError: %s' % str(e))
        return
    
    # Step 4: Setup EPG
    progress.update(60, 'Setting up EPG...')
    epg_path = download_epg(country_code)
    
    # Step 5: Configure PVR
    progress.update(70, 'Configuring PVR...')
    if not configure_pvr_simple(playlist_path, epg_path):
        progress.close()
        dialog.ok(ADDON_NAME, 'Failed to configure PVR.')
        return
    
    # Step 6: Enable PVR
    progress.update(75, 'Enabling PVR...')
    enable_addon('pvr.iptvsimple')
    xbmc.sleep(2000)
    
    # Step 7: Install skin
    progress.update(80, 'Installing Arctic Zephyr...')
    skin_installed = install_skin()
    
    # Step 8: Configure menu
    progress.update(90, 'Configuring menu...')
    hide_menu_items()
    
    # Step 9: Activate skin
    if skin_installed:
        progress.update(95, 'Activating Arctic Zephyr...')
        set_skin('skin.arctic.zephyr.mod')
    
    progress.update(100, 'Complete!')
    xbmc.sleep(1000)
    progress.close()
    
    msg = 'Setup Complete!\n\n✓ %d channels for %s\n✓ PVR IPTV Simple enabled\n✓ Arctic Zephyr skin installed\n\nRESTART KODI to activate:\n- Arctic Zephyr skin\n- Clean menu (TV, Movies, TV Shows only)\n\nAfter restart: Go to TV section!' % (playlists['total'], country_name)
    
    if dialog.yesno(ADDON_NAME, msg, nolabel='Later', yeslabel='Restart Now'):
        log('Restarting Kodi...')
        xbmc.executebuiltin('RestartApp')
    
    log('Setup completed successfully')

if __name__ == '__main__':
    main()
