"""
Plotting script for visualizing collected data
"""
import logging
import sys
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from .db import Database
from .config import SYMBOLS, TIMEFRAME

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Plotter:
    """Data plotting class"""
    
    def __init__(self):
        """Initialize plotter"""
        self.db = Database()
    
    def plot_ohlcv(self, symbol: str, hours: int = 24, save_path: str = None):
        """
        Plot OHLCV candlestick chart
        
        Args:
            symbol: Trading pair to plot
            hours: Number of hours of data to show
            save_path: Optional path to save the plot
        """
        self.db.connect()
        
        # Calculate time range
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - (hours * 3600 * 1000)
        
        # Fetch data
        data = self.db.get_ohlcv(symbol, TIMEFRAME, start_time=start_time, end_time=end_time)
        
        if not data:
            logger.error(f"No data found for {symbol} in the last {hours} hours")
            return
        
        # Extract data
        timestamps = [datetime.fromtimestamp(d['timestamp'] / 1000) for d in data]
        opens = [d['open'] for d in data]
        highs = [d['high'] for d in data]
        lows = [d['low'] for d in data]
        closes = [d['close'] for d in data]
        volumes = [d['volume'] for d in data]
        
        # Create figure with subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[3, 1])
        fig.suptitle(f'{symbol} - {TIMEFRAME} ({hours}h)', fontsize=14, fontweight='bold')
        
        # Plot candlesticks
        for i, (ts, open_p, high, low, close) in enumerate(zip(timestamps, opens, highs, lows, closes)):
            color = 'green' if close >= open_p else 'red'
            ax1.plot([ts, ts], [low, high], color='black', linewidth=0.5)
            ax1.plot([ts, ts], [open_p, close], color=color, linewidth=2)
        
        ax1.set_ylabel('Price', fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax1.xaxis.set_major_locator(mdates.HourLocator(interval=max(1, hours // 12)))
        
        # Plot volume
        ax2.bar(timestamps, volumes, width=timedelta(minutes=1), alpha=0.6, color='blue')
        ax2.set_ylabel('Volume', fontweight='bold')
        ax2.set_xlabel('Time', fontweight='bold')
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax2.xaxis.set_major_locator(mdates.HourLocator(interval=max(1, hours // 12)))
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            logger.info(f"Plot saved to {save_path}")
        else:
            plt.show()
        
        plt.close()
    
    def plot_price_trend(self, symbol: str, hours: int = 24, save_path: str = None):
        """
        Plot simple price trend line
        
        Args:
            symbol: Trading pair to plot
            hours: Number of hours of data to show
            save_path: Optional path to save the plot
        """
        self.db.connect()
        
        # Calculate time range
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - (hours * 3600 * 1000)
        
        # Fetch data
        data = self.db.get_ohlcv(symbol, TIMEFRAME, start_time=start_time, end_time=end_time)
        
        if not data:
            logger.error(f"No data found for {symbol} in the last {hours} hours")
            return
        
        # Extract data
        timestamps = [datetime.fromtimestamp(d['timestamp'] / 1000) for d in data]
        closes = [d['close'] for d in data]
        
        # Create plot
        plt.figure(figsize=(12, 6))
        plt.plot(timestamps, closes, linewidth=1.5, label='Close Price')
        plt.title(f'{symbol} Price Trend - {TIMEFRAME} ({hours}h)', fontsize=14, fontweight='bold')
        plt.xlabel('Time', fontweight='bold')
        plt.ylabel('Price', fontweight='bold')
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.xticks(rotation=45)
        plt.gcf().autofmt_xdate()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            logger.info(f"Plot saved to {save_path}")
        else:
            plt.show()
        
        plt.close()
    
    def plot_all_symbols(self, hours: int = 24, save_dir: str = None):
        """
        Plot all configured symbols
        
        Args:
            hours: Number of hours of data to show
            save_dir: Optional directory to save plots
        """
        for symbol in SYMBOLS:
            symbol = symbol.strip()
            save_path = None
            if save_dir:
                from pathlib import Path
                save_dir_path = Path(save_dir)
                save_dir_path.mkdir(exist_ok=True)
                save_path = save_dir_path / f"{symbol.replace('/', '_')}_{hours}h.png"
            
            logger.info(f"Plotting {symbol}...")
            try:
                self.plot_ohlcv(symbol, hours=hours, save_path=str(save_path) if save_path else None)
            except Exception as e:
                logger.error(f"Error plotting {symbol}: {e}")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Plot market data')
    parser.add_argument('--symbol', type=str, help='Symbol to plot (default: all)')
    parser.add_argument('--hours', type=int, default=24, help='Hours of data to show (default: 24)')
    parser.add_argument('--save', type=str, help='Path to save plot (optional)')
    parser.add_argument('--type', type=str, choices=['ohlcv', 'trend'], default='ohlcv',
                       help='Plot type (default: ohlcv)')
    
    args = parser.parse_args()
    
    plotter = Plotter()
    
    if args.symbol:
        if args.type == 'ohlcv':
            plotter.plot_ohlcv(args.symbol, hours=args.hours, save_path=args.save)
        else:
            plotter.plot_price_trend(args.symbol, hours=args.hours, save_path=args.save)
    else:
        plotter.plot_all_symbols(hours=args.hours, save_dir=args.save)


if __name__ == "__main__":
    main()

