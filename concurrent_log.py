#!/usr/bin/env python3

import subprocess
import threading
import time
import csv
import re
import sys
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import signal

class NetworkMonitor:
    def __init__(self, target_ip, interface="wlan0", duration=3600, interval=5, output_file=None):
        self.target_ip = target_ip
        self.interface = interface
        self.duration = duration  # Duration in seconds
        self.interval = interval  # Sample interval in seconds
        self.output_file = output_file or f"network_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.running = True
        self.data_lock = threading.Lock()
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        print("\nReceived interrupt signal. Stopping monitoring...")
        self.running = False
    
    def run_command(self, command):
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            return result.stdout.strip() if result.returncode == 0 else ""
        except subprocess.TimeoutExpired:
            return ""
        except Exception:
            return ""
    
    def get_ping_latency(self):
        command = f"ping -c 1 -W 1 {self.target_ip}"
        output = self.run_command(command)
        
        match = re.search(r'time=([0-9.]+)', output)
        return float(match.group(1)) if match else None
    
    def get_link_info(self):
        command = f"iw dev {self.interface} link"
        output = self.run_command(command)
        
        rx_match = re.search(r'rx bitrate:\s+([0-9.]+)\s+MBit/s', output)
        rx_bitrate = float(rx_match.group(1)) if rx_match else None
        
        tx_match = re.search(r'tx bitrate:\s+([0-9.]+)\s+MBit/s', output)
        tx_bitrate = float(tx_match.group(1)) if tx_match else None
        
        signal_match = re.search(r'signal:\s+(-?[0-9]+)\s+dBm', output)
        signal_strength = int(signal_match.group(1)) if signal_match else None
        
        return rx_bitrate, tx_bitrate, signal_strength
    
    def get_interface_info(self):
        command = f"iw dev {self.interface} info"
        output = self.run_command(command)
        
        freq_match = re.search(r'channel\s+\d+\s+\((\d+)\s+MHz\)', output)
        frequency = int(freq_match.group(1)) if freq_match else None
        
        width_match = re.search(r'width:\s+(\d+)\s+MHz', output)
        width = int(width_match.group(1)) if width_match else None
        
        center_match = re.search(r'center1:\s+(\d+)\s+MHz', output)
        centre_frequency = int(center_match.group(1)) if center_match else frequency
        
        power_match = re.search(r'txpower\s+([0-9.]+)\s+dBm', output)
        tx_power = float(power_match.group(1)) if power_match else None
        
        return frequency, width, centre_frequency, tx_power
    
    def collect_data_sample(self):
        with ThreadPoolExecutor(max_workers=3) as executor:
            ping_future = executor.submit(self.get_ping_latency)
            link_future = executor.submit(self.get_link_info)
            info_future = executor.submit(self.get_interface_info)
    
            latency = ping_future.result()
            rx_bitrate, tx_bitrate, signal_strength = link_future.result()
            frequency, width, centre_frequency, tx_power = info_future.result()
        
        return {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'latency_ms': latency,
            'rx_bitrate_mbps': rx_bitrate,
            'tx_bitrate_mbps': tx_bitrate,
            'signal_strength_dbm': signal_strength,
            'frequency_mhz': frequency,
            'width_mhz': width,
            'centre_frequency_mhz': centre_frequency,
            'tx_power_dbm': tx_power
        }
    
    def write_csv_header(self):
        fieldnames = [
            'timestamp', 'latency_ms', 'rx_bitrate_mbps', 'tx_bitrate_mbps',
            'signal_strength_dbm', 'frequency_mhz', 'width_mhz', 
            'centre_frequency_mhz', 'tx_power_dbm'
        ]
        
        with open(self.output_file, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
    
    def write_data_row(self, data):
        fieldnames = [
            'timestamp', 'latency_ms', 'rx_bitrate_mbps', 'tx_bitrate_mbps',
            'signal_strength_dbm', 'frequency_mhz', 'width_mhz', 
            'centre_frequency_mhz', 'tx_power_dbm'
        ]
        
        with self.data_lock:
            with open(self.output_file, 'a', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writerow(data)
    
    def format_time(self, seconds):
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def run(self):
        print("Starting network monitoring...")
        print(f"Target IP: {self.target_ip}")
        print(f"Interface: {self.interface}")
        print(f"Duration: {self.duration} seconds ({self.duration//60} minutes)")
        print(f"Output file: {self.output_file}")
        print(f"Sampling every {self.interval} seconds")
        print("Press Ctrl+C to stop early")
        print()
        
        self.write_csv_header()
        
        start_time = time.time()
        end_time = start_time + self.duration
        
        try:
            while self.running and time.time() < end_time:
                data = self.collect_data_sample()
                self.write_data_row(data)
                
                current_time = time.time()
                elapsed = int(current_time - start_time)
                remaining = int(end_time - current_time)
                
                print(f"\rElapsed: {self.format_time(elapsed)} | "
                      f"Remaining: {self.format_time(remaining)} | "
                      f"Latest ping: {data['latency_ms'] or 'N/A'}ms", end='', flush=True)
                
                time.sleep(self.interval)
                
        except KeyboardInterrupt:
            self.running = False
        
        print(f"\nMonitoring completed!")
        print(f"Data saved to: {self.output_file}")

def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Monitor network metrics (ping, wireless link info) and log to CSV',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s 192.168.1.1                    # Monitor ping to 192.168.1.1
  %(prog)s 8.8.8.8 -i wlan1               # Monitor ping to 8.8.8.8 on wlan1 interface
  %(prog)s 192.168.0.1 -d 1800 -s 10      # Monitor for 30 minutes, sample every 10 seconds
        '''
    )
    
    parser.add_argument('ip', 
                       help='Target IP address to ping')
    
    parser.add_argument('-i', '--interface', 
                       default='wlan0',
                       help='Wireless interface to monitor (default: wlan0)')
    
    parser.add_argument('-d', '--duration', 
                       type=int, 
                       default=3600,
                       help='Monitoring duration in seconds (default: 3600 = 1 hour)')
    
    parser.add_argument('-s', '--interval', 
                       type=int, 
                       default=5,
                       help='Sampling interval in seconds (default: 5)')
    
    parser.add_argument('-o', '--output',
                       help='Output CSV filename (default: auto-generated with timestamp)')
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    if args.output:
        output_file = args.output
    else:
        output_file = f"network_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    print(f"Network Monitor Configuration:")
    print(f"  Target IP: {args.ip}")
    print(f"  Interface: {args.interface}")
    print(f"  Duration: {args.duration} seconds ({args.duration//60} minutes)")
    print(f"  Interval: {args.interval} seconds")
    print(f"  Output: {output_file}")
    print()
    
    monitor = NetworkMonitor(
        target_ip=args.ip,
        interface=args.interface,
        duration=args.duration,
        interval=args.interval,
        output_file=output_file
    )
    
    monitor.run()

if __name__ == "__main__":
    main()
