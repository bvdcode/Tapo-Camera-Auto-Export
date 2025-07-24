# tapo_video_downloader.py - COMPLETE VIDEO DOWNLOADER
"""
🎬 TAPO C200 VIDEO DOWNLOADER

This script:
1. ✅ Connects to Tapo C200 camera
2. ✅ Finds all recordings on SD card  
3. ✅ Downloads them to folder with filename format: 20250724_161234-123456789.mp4
4. ⚠️  Attempts to delete recordings from camera (experimental)
5. ✅ Shows download progress

WARNING: The pytapo.media_stream.downloader module is experimental!
Make sure you have backup copies of important recordings!

Author: Vadim Belov
"""

import os
import asyncio
import argparse
from datetime import datetime
from pytapo import Tapo
from pytapo.media_stream.downloader import Downloader

# ==================== SETTINGS ====================
DEFAULT_USER = "admin"  # Default user for most Tapo cameras
DELETE_AFTER_DOWNLOAD = False  # Set True to delete from camera after download
WINDOW_SIZE = 1000  # Download window size (affects speed)
# ===================================================


def format_filename(timestamp):
    """Formats timestamp to required format 20250724_161234-123456789.mp4"""
    dt = datetime.fromtimestamp(timestamp)
    local_time = dt.strftime("%Y%m%d_%H%M%S")
    unix_timestamp = int(timestamp)
    return f"{local_time}-{unix_timestamp}.mp4"


def get_date_folder(timestamp):
    """Creates path to date folder in format YYYY\MM\DD"""
    dt = datetime.fromtimestamp(timestamp)
    return os.path.join(dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d"))


def extract_dates(dates_data):
    """Extracts dates from getRecordingsList() response"""
    dates = []
    if isinstance(dates_data, list):
        for item in dates_data:
            if isinstance(item, dict):
                for key, value in item.items():
                    if key.startswith('search_results_') and isinstance(value, dict) and 'date' in value:
                        dates.append(value['date'])
    return dates


def extract_recordings(recordings_data):
    """Extracts recordings from getRecordings() response"""
    recordings = []
    if isinstance(recordings_data, list):
        for item in recordings_data:
            if isinstance(item, dict):
                for key, value in item.items():
                    if key.startswith('search_video_results_') and isinstance(value, dict):
                        if 'startTime' in value and 'endTime' in value:
                            recordings.append(value)
    return recordings


async def download_recording(tapo, recording, base_output_dir, time_correction, index, total):
    """Downloads a single recording"""
    start_time = recording['startTime']
    end_time = recording['endTime']
    video_type = recording.get('vedio_type', 'unknown')
    duration = end_time - start_time

    # Create date folder
    date_folder = get_date_folder(start_time)
    output_dir = os.path.join(base_output_dir, date_folder)
    os.makedirs(output_dir, exist_ok=True)

    filename = format_filename(start_time)
    filepath = os.path.join(output_dir, filename)

    # Check if file already exists
    if os.path.exists(filepath):
        file_size = os.path.getsize(filepath)
        display_path = date_folder.replace(os.sep, "\\")
        print(f"\n[{index:3d}/{total}] ⏭️  {display_path}\\{filename}")
        print(
            f"           📁 File already exists ({file_size} bytes) - skipping")
        return "skipped"

    display_path = date_folder.replace(os.sep, "\\")
    print(f"\n[{index:3d}/{total}] 📥 {display_path}\\{filename}")
    print(f"           ⏱️  Duration: {duration}s, Type: {video_type}")

    try:
        downloader = Downloader(
            tapo,
            start_time,
            end_time,
            time_correction,
            output_dir + os.sep,
            fileName=filename,
            window_size=WINDOW_SIZE
        )

        last_percent = -1
        async for status in downloader.download():
            action = status["currentAction"]
            progress = status.get("progress", 0)
            total_time = status.get("total", 0)

            if total_time > 0:
                percent = int((progress / total_time) * 100)
                # Show progress only when changed by 5%
                if percent != last_percent and percent % 5 == 0:
                    bar_length = 20
                    filled = int(bar_length * percent / 100)
                    bar = "█" * filled + "░" * (bar_length - filled)
                    print(f"           {action}: [{bar}] {percent}%")
                    last_percent = percent
            else:
                if action != "Downloading":
                    print(f"           {action}...")

        print(f"           ✅ Downloaded successfully")
        return True

    except Exception as e:
        print(f"           ❌ Download error: {e}")
        return False


async def try_delete_recording(tapo, recording):
    """Attempts to delete recording from camera"""
    if not DELETE_AFTER_DOWNLOAD:
        return False

    try:
        # Try different API variants for deletion
        delete_attempts = [
            {
                "method": "deleteRecording",
                "params": {
                    "playback": {
                        "delete_video": {
                            "channel": 0,
                            "start_time": str(recording['startTime']),
                            "end_time": str(recording['endTime'])
                        }
                    }
                }
            },
            {
                "method": "do",
                "params": {
                    "playback": {
                        "delete": {
                            "start_time": recording['startTime'],
                            "end_time": recording['endTime']
                        }
                    }
                }
            }
        ]

        for attempt in delete_attempts:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, tapo.executeFunction, attempt["method"], attempt["params"]
                )
                print(f"           🗑️ Deleted from camera")
                return True
            except Exception:
                continue

        print(f"           ⚠️ Deletion not supported")
        return False

    except Exception as e:
        print(f"           ⚠️ Deletion error: {e}")
        return False


async def download_all_videos(tapo, output_dir):
    """Main function for downloading all videos"""
    print("📊 Scanning camera SD card...")

    # Create base output folder if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 Output folder: {output_dir}")

    # Get all dates with recordings
    dates_data = await asyncio.get_event_loop().run_in_executor(
        None, tapo.getRecordingsList
    )
    dates = extract_dates(dates_data)
    print(f"📅 Found dates with recordings: {len(dates)}")

    if not dates:
        print("❌ No recordings found on camera")
        return

    # Collect all recordings
    all_recordings = []
    total_duration = 0

    for date in dates:
        recordings_data = await asyncio.get_event_loop().run_in_executor(
            None, tapo.getRecordings, date
        )
        recordings = extract_recordings(recordings_data)
        all_recordings.extend(recordings)

        date_duration = sum(r['endTime'] - r['startTime'] for r in recordings)
        total_duration += date_duration

        print(
            f"  📅 {date}: {len(recordings):2d} recordings, {date_duration//60:3d}min {date_duration % 60:2d}sec")

    total_count = len(all_recordings)
    hours = total_duration // 3600
    minutes = (total_duration % 3600) // 60
    seconds = total_duration % 60

    print(f"\n📊 TOTAL TO DOWNLOAD:")
    print(f"  📼 Recordings: {total_count}")
    print(f"  ⏱️  Total duration: {hours}h {minutes}min {seconds}sec")
    print(f"  📁 Base folder: {output_dir}")
    print(f"  📂 Structure: YYYY\\MM\\DD (example: 2025\\07\\24)")

    if total_count == 0:
        print("❌ No recordings to download")
        return

    # Get time correction
    time_correction = await asyncio.get_event_loop().run_in_executor(
        None, tapo.getTimeCorrection
    )

    print(f"\n🚀 STARTING DOWNLOAD...")
    if DELETE_AFTER_DOWNLOAD:
        print("⚠️  WARNING: Recordings will be deleted from camera after download!")

    # Download all recordings
    successful = 0
    failed = 0
    skipped = 0
    deleted = 0
    start_time = datetime.now()

    for i, recording in enumerate(all_recordings, 1):
        result = await download_recording(tapo, recording, output_dir, time_correction, i, total_count)

        if result == "skipped":
            skipped += 1
        elif result == True:
            successful += 1
            # Try to delete only successfully downloaded files
            if await try_delete_recording(tapo, recording):
                deleted += 1
        else:
            failed += 1

        # Show intermediate statistics every 10 files
        if i % 10 == 0 or i == total_count:
            elapsed = datetime.now() - start_time
            remaining = total_count - i
            if i > 0:
                avg_time = elapsed.total_seconds() / i
                eta_seconds = remaining * avg_time
                eta = f"{int(eta_seconds//3600)}h {int((eta_seconds % 3600)//60)}min"
            else:
                eta = "unknown"

            print(
                f"\n📈 Progress: ✅{successful} | ⏭️{skipped} | ❌{failed} | Remaining: {remaining} | ETA: {eta}")

    # Final statistics
    total_time = datetime.now() - start_time
    print(f"\n" + "=" * 60)
    print(f"🎉 DOWNLOAD COMPLETED!")
    print(f"  ✅ Successfully downloaded: {successful}")
    print(f"  ⏭️ Skipped (already exists): {skipped}")
    print(f"  ❌ Download errors: {failed}")
    if DELETE_AFTER_DOWNLOAD:
        print(f"  🗑️ Deleted from camera: {deleted}")
    print(f"  ⏱️  Total time: {total_time}")
    print(f"  📁 Files saved to: {output_dir}")
    print(f"  📂 Folder structure: YYYY\\MM\\DD")

    if successful > 0:
        print(f"\n💡 Filename format: YYYYMMDD_HHMMSS-UNIX_TIMESTAMP.mp4")
        print(f"   Example: 20250724_161234-1721829154.mp4")
        print(
            f"   Location: {output_dir}\\2025\\07\\24\\20250724_161234-1721829154.mp4")


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Download all videos from Tapo C200 camera",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py 192.168.1.100 mypassword
  python main.py 192.168.1.100 mypassword --user myuser
  python main.py 192.168.1.100 mypassword --output /path/to/videos
  python main.py 192.168.1.100 mypassword --delete
        """
    )

    parser.add_argument('ip', help='Camera IP address')
    parser.add_argument('password', help='Camera password')
    parser.add_argument('--user', '-u', default=DEFAULT_USER,
                        help=f'Camera username (default: {DEFAULT_USER})')
    parser.add_argument('--output', '-o', default=os.getcwd(),
                        help='Output directory (default: current directory)')
    parser.add_argument('--delete', '-d', action='store_true',
                        help='Delete videos from camera after download (experimental)')

    return parser.parse_args()


def main():
    """Main function"""
    args = parse_arguments()

    # Set global delete flag
    global DELETE_AFTER_DOWNLOAD
    DELETE_AFTER_DOWNLOAD = args.delete

    print("🎬 TAPO C200 VIDEO DOWNLOADER")
    print("=" * 50)
    print(f"📷 Camera: {args.ip}")
    print(f"👤 User: {args.user}")
    print(f"📁 Output: {args.output}")
    print(
        f"🗑️ Delete after download: {'YES' if DELETE_AFTER_DOWNLOAD else 'NO'}")
    print("=" * 50)

    try:
        print("🔌 Connecting to camera...")
        # Create Tapo object OUTSIDE async context
        tapo = Tapo(args.ip, args.user, args.password,
                    args.password, printDebugInformation=False)
        print("✅ Connection successful")

        # Run async download
        asyncio.run(download_all_videos(tapo, args.output))

    except KeyboardInterrupt:
        print("\n⛔ Download interrupted by user")
        print("💡 Already downloaded files are saved")
    except Exception as e:
        print(f"\n💥 Critical error: {e}")
        print("💡 Check IP, login, password settings")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
