#!/usr/bin/env python3

import subprocess
import threading
import time
import csv
import re
import sys
import argparse
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import signal
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

class NetworkMonitor:
    def __init__(self, target_ip, interface="wlan0", duration=3600, interval=5, output_file=None, plot_dir=None):
        self.target_ip = target_ip
        self.interface = interface
        self.duration = duration  # Duration in seconds
        self.interval = interval  # Sample interval in seconds
        self.output_file = output_file or f"network_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.plot_dir = plot_dir or f"network_plots_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.running = True
        self.data_lock = threading.Lock()
        
        # Create plot directory
        os.makedirs(self.plot_dir, exist_ok=True)
        
        # Setup signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        print("\nReceived interrupt signal. Stopping monitoring...")
        self.running = False
    
    def run_command(self, command):
        """Run a shell command and return its output"""
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            return result.stdout.strip() if result.returncode == 0 else ""
        except subprocess.TimeoutExpired:
            return ""
        except Exception:
            return ""
    
    def get_ping_latency(self):
        """Extract ping latency in milliseconds"""
        command = f"ping -c 1 -W 1 {self.target_ip}"
        output = self.run_command(command)
        
        # Look for time=X.XXX pattern
        match = re.search(r'time=([0-9.]+)', output)
        return float(match.group(1)) if match else None
    
    def get_link_info(self):
        """Extract RX/TX bitrate and signal strength from iw link"""
        command = f"iw dev {self.interface} link"
        output = self.run_command(command)
        
        # Extract RX bitrate
        rx_match = re.search(r'rx bitrate:\s+([0-9.]+)\s+MBit/s', output)
        rx_bitrate = float(rx_match.group(1)) if rx_match else None
        
        # Extract TX bitrate
        tx_match = re.search(r'tx bitrate:\s+([0-9.]+)\s+MBit/s', output)
        tx_bitrate = float(tx_match.group(1)) if tx_match else None
        
        # Extract signal strength
        signal_match = re.search(r'signal:\s+(-?[0-9]+)\s+dBm', output)
        signal_strength = int(signal_match.group(1)) if signal_match else None
        
        return rx_bitrate, tx_bitrate, signal_strength
    
    def get_interface_info(self):
        """Extract frequency, width, centre frequency, and TX power from iw info"""
        command = f"iw dev {self.interface} info"
        output = self.run_command(command)
        
        # Extract frequency
        freq_match = re.search(r'channel\s+\d+\s+\((\d+)\s+MHz\)', output)
        frequency = int(freq_match.group(1)) if freq_match else None
        
        # Extract channel width
        width_match = re.search(r'width:\s+(\d+)\s+MHz', output)
        width = int(width_match.group(1)) if width_match else None
        
        # Extract center frequency
        center_match = re.search(r'center1:\s+(\d+)\s+MHz', output)
        centre_frequency = int(center_match.group(1)) if center_match else frequency
        
        # Extract TX power
        power_match = re.search(r'txpower\s+([0-9.]+)\s+dBm', output)
        tx_power = float(power_match.group(1)) if power_match else None
        
        return frequency, width, centre_frequency, tx_power
    
    def collect_data_sample(self):
        """Collect one sample of data from all three commands concurrently"""
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit all three tasks concurrently
            ping_future = executor.submit(self.get_ping_latency)
            link_future = executor.submit(self.get_link_info)
            info_future = executor.submit(self.get_interface_info)
            
            # Wait for all tasks to complete
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
        """Write CSV header to output file"""
        fieldnames = [
            'timestamp', 'latency_ms', 'rx_bitrate_mbps', 'tx_bitrate_mbps',
            'signal_strength_dbm', 'frequency_mhz', 'width_mhz', 
            'centre_frequency_mhz', 'tx_power_dbm'
        ]
        
        with open(self.output_file, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
    
    def write_data_row(self, data):
        """Append data row to CSV file"""
        fieldnames = [
            'timestamp', 'latency_ms', 'rx_bitrate_mbps', 'tx_bitrate_mbps',
            'signal_strength_dbm', 'frequency_mhz', 'width_mhz', 
            'centre_frequency_mhz', 'tx_power_dbm'
        ]
        
        with self.data_lock:
            with open(self.output_file, 'a', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writerow(data)
    
    def calculate_statistics(self, data, column_name):
        """Calculate min, mean, max for a data column"""
        valid_data = [x for x in data if x is not None and not pd.isna(x)]
        if not valid_data:
            return None, None, None
        
        return np.min(valid_data), np.mean(valid_data), np.max(valid_data)
    
    def create_plots(self):
        """Generate plots for each data category"""
        print(f"\nGenerating plots and calculating statistics...")
        
        # Read the CSV data
        try:
            df = pd.read_csv(self.output_file)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        except Exception as e:
            print(f"Error reading CSV file: {e}")
            return
        
        # Configure matplotlib for better appearance
        plt.style.use('default')
        plt.rcParams['figure.figsize'] = (12, 8)
        plt.rcParams['font.size'] = 10
        
        # Define plot configurations
        plot_configs = [
            {
                'column': 'latency_ms',
                'title': 'Ping Latency Over Time',
                'ylabel': 'Latency (ms)',
                'color': '#2E86C1',
                'filename': 'latency.png'
            },
            {
                'column': 'rx_bitrate_mbps',
                'title': 'RX Bitrate Over Time',
                'ylabel': 'RX Bitrate (Mbps)',
                'color': '#28B463',
                'filename': 'rx_bitrate.png'
            },
            {
                'column': 'tx_bitrate_mbps',
                'title': 'TX Bitrate Over Time',
                'ylabel': 'TX Bitrate (Mbps)',
                'color': '#E74C3C',
                'filename': 'tx_bitrate.png'
            },
            {
                'column': 'signal_strength_dbm',
                'title': 'Signal Strength Over Time',
                'ylabel': 'Signal Strength (dBm)',
                'color': '#8E44AD',
                'filename': 'signal_strength.png'
            },
            {
                'column': 'frequency_mhz',
                'title': 'Operating Frequency Over Time',
                'ylabel': 'Frequency (MHz)',
                'color': '#F39C12',
                'filename': 'frequency.png'
            },
            {
                'column': 'width_mhz',
                'title': 'Channel Width Over Time',
                'ylabel': 'Width (MHz)',
                'color': '#17A2B8',
                'filename': 'channel_width.png'
            },
            {
                'column': 'centre_frequency_mhz',
                'title': 'Centre Frequency Over Time',
                'ylabel': 'Centre Frequency (MHz)',
                'color': '#FD7E14',
                'filename': 'centre_frequency.png'
            },
            {
                'column': 'tx_power_dbm',
                'title': 'TX Power Over Time',
                'ylabel': 'TX Power (dBm)',
                'color': '#6F42C1',
                'filename': 'tx_power.png'
            }
        ]
        
        print("\nStatistical Summary:")
        print("=" * 60)
        
        # Create individual plots
        for config in plot_configs:
            column = config['column']
            
            # Skip if column doesn't exist or has no data
            if column not in df.columns:
                continue
                
            # Calculate statistics
            min_val, mean_val, max_val = self.calculate_statistics(df[column], column)
            
            if min_val is None:
                print(f"{config['title']:<30}: No valid data")
                continue
            
            # Print statistics
            print(f"{config['title']:<30}: Min={min_val:.2f}, Mean={mean_val:.2f}, Max={max_val:.2f}")
            
            # Create plot
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # Plot the data
            valid_mask = df[column].notna()
            ax.plot(df.loc[valid_mask, 'timestamp'], 
                   df.loc[valid_mask, column], 
                   color=config['color'], 
                   linewidth=1.5, 
                   alpha=0.8,
                   label=f'{column.replace("_", " ").title()}')
            
            # Add horizontal lines for min, mean, max
            ax.axhline(y=mean_val, color='red', linestyle='--', alpha=0.7, label=f'Mean: {mean_val:.2f}')
            ax.axhline(y=min_val, color='green', linestyle=':', alpha=0.7, label=f'Min: {min_val:.2f}')
            ax.axhline(y=max_val, color='orange', linestyle=':', alpha=0.7, label=f'Max: {max_val:.2f}')
            
            # Formatting
            ax.set_title(config['title'], fontsize=14, fontweight='bold', pad=20)
            ax.set_xlabel('Time', fontsize=12)
            ax.set_ylabel(config['ylabel'], fontsize=12)
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right', framealpha=0.9)
            
            # Format x-axis
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=max(1, len(df) // 20)))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
            
            # Tight layout and save
            plt.tight_layout()
            plot_path = os.path.join(self.plot_dir, config['filename'])
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            plt.close()
        
        # Create a combined overview plot
        self.create_overview_plot(df, plot_configs)
        
        print("=" * 60)
        print(f"Plots saved to directory: {self.plot_dir}")
    
    def create_overview_plot(self, df, plot_configs):
        """Create a combined overview plot with all metrics"""
        fig, axes = plt.subplots(2, 4, figsize=(20, 12))
        axes = axes.flatten()
        
        fig.suptitle('Network Monitoring Overview', fontsize=16, fontweight='bold')
        
        for i, config in enumerate(plot_configs):
            if i >= len(axes):
                break
            
            column = config['column']
            ax = axes[i]
            
            if column not in df.columns:
                ax.text(0.5, 0.5, 'No Data', ha='center', va='center', transform=ax.transAxes)
                ax.set_title(config['title'])
                continue
            
            valid_mask = df[column].notna()
            if not valid_mask.any():
                ax.text(0.5, 0.5, 'No Valid Data', ha='center', va='center', transform=ax.transAxes)
                ax.set_title(config['title'])
                continue
            
            # Plot data
            ax.plot(df.loc[valid_mask, 'timestamp'], 
                   df.loc[valid_mask, column], 
                   color=config['color'], 
                   linewidth=1, 
                   alpha=0.8)
            
            # Calculate and add mean line
            mean_val = df[column].mean()
            if not pd.isna(mean_val):
                ax.axhline(y=mean_val, color='red', linestyle='--', alpha=0.5)
            
            ax.set_title(config['title'], fontsize=10)
            ax.set_ylabel(config['ylabel'], fontsize=9)
            ax.grid(True, alpha=0.3)
            ax.tick_params(axis='x', labelsize=8, rotation=45)
            ax.tick_params(axis='y', labelsize=8)
        
        plt.tight_layout()
        overview_path = os.path.join(self.plot_dir, 'overview.png')
        plt.savefig(overview_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Overview plot saved as: overview.png")
    
    def format_time(self, seconds):
        """Format seconds into HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def run(self):
        """Main monitoring loop"""
        print("Starting network monitoring...")
        print(f"Target IP: {self.target_ip}")
        print(f"Interface: {self.interface}")
        print(f"Duration: {self.duration} seconds ({self.duration//60} minutes)")
        print(f"Output file: {self.output_file}")
        print(f"Plot directory: {self.plot_dir}")
        print(f"Sampling every {self.interval} seconds")
        print("Press Ctrl+C to stop early")
        print()
        
        # Initialize CSV file
        self.write_csv_header()
        
        start_time = time.time()
        end_time = start_time + self.duration
        
        try:
            while self.running and time.time() < end_time:
                # Collect data sample
                data = self.collect_data_sample()
                
                # Write to CSV
                self.write_data_row(data)
                
                # Display progress
                current_time = time.time()
                elapsed = int(current_time - start_time)
                remaining = int(end_time - current_time)
                
                print(f"\rElapsed: {self.format_time(elapsed)} | "
                      f"Remaining: {self.format_time(remaining)} | "
                      f"Latest ping: {data['latency_ms'] or 'N/A'}ms", end='', flush=True)
                
                # Wait for next interval
                time.sleep(self.interval)
                
        except KeyboardInterrupt:
            self.running = False
        
        print(f"\nMonitoring completed!")
        print(f"Data saved to: {self.output_file}")
        
        # Generate plots and statistics
        self.create_plots()

def parse_arguments():
    """Parse command line arguments"""
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
    
    parser.add_argument('-p', '--plot-dir',
                       help='Directory to save plots (default: auto-generated with timestamp)')
    
    return parser.parse_args()

def main():
    # Parse command line arguments
    args = parse_arguments()
    
    # Use provided output filename or generate one
    if args.output:
        output_file = args.output
    else:
        output_file = f"network_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    # Use provided plot directory or generate one
    plot_dir = args.plot_dir or f"network_plots_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print(f"Network Monitor Configuration:")
    print(f"  Target IP: {args.ip}")
    print(f"  Interface: {args.interface}")
    print(f"  Duration: {args.duration} seconds ({args.duration//60} minutes)")
    print(f"  Interval: {args.interval} seconds")
    print(f"  Output: {output_file}")
    print(f"  Plot Directory: {plot_dir}")
    print()
    
    # Check for required dependencies
    try:
        import matplotlib.pyplot as plt
        import pandas as pd
        import numpy as np
    except ImportError as e:
        print(f"Error: Missing required dependency: {e}")
        print("Please install required packages:")
        print("  pip install matplotlib pandas numpy")
        sys.exit(1)
    
    # Create and run monitor
    monitor = NetworkMonitor(
        target_ip=args.ip,
        interface=args.interface,
        duration=args.duration,
        interval=args.interval,
        output_file=output_file,
        plot_dir=plot_dir
    )
    
    monitor.run()

if __name__ == "__main__":
    main()
