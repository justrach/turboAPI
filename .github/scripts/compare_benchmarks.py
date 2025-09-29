#!/usr/bin/env python3
"""
Benchmark Comparison Script for TurboAPI
Compares current performance with historical data and generates trends
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import statistics

def load_performance_history():
    """Load historical performance data."""
    history_file = Path('performance_history.json')
    
    if not history_file.exists():
        print("📊 No historical performance data found")
        return []
    
    try:
        with open(history_file, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"⚠️ Invalid historical data: {e}")
        return []

def analyze_performance_trends(historical_data):
    """Analyze performance trends over time."""
    if len(historical_data) < 2:
        print("📊 Insufficient data for trend analysis")
        return {}
    
    # Sort by timestamp
    sorted_data = sorted(historical_data, key=lambda x: x.get('timestamp', ''))
    
    trends = {}
    
    # Analyze key metrics
    metrics_to_analyze = [
        'test_success_rate',
        'total_duration',
        'middleware_pipeline_duration',
        'zero-copy_optimizations_duration',
        'server_startup_duration'
    ]
    
    for metric in metrics_to_analyze:
        values = []
        timestamps = []
        
        for entry in sorted_data:
            if metric in entry:
                values.append(entry[metric])
                timestamps.append(entry.get('timestamp', ''))
        
        if len(values) >= 2:
            # Calculate trend (simple linear regression slope)
            n = len(values)
            if n > 1:
                # Recent vs older average
                recent_avg = statistics.mean(values[-5:]) if len(values) >= 5 else statistics.mean(values[-2:])
                older_avg = statistics.mean(values[:5]) if len(values) >= 10 else statistics.mean(values[:-2])
                
                if older_avg != 0:
                    trend_percent = ((recent_avg - older_avg) / older_avg) * 100
                    trends[metric] = {
                        'recent_avg': recent_avg,
                        'older_avg': older_avg,
                        'trend_percent': trend_percent,
                        'data_points': n
                    }
    
    return trends

def generate_performance_dashboard(historical_data, trends):
    """Generate performance dashboard data."""
    dashboard = {
        'generated_at': datetime.now().isoformat(),
        'total_runs': len(historical_data),
        'date_range': {
            'start': min(entry.get('timestamp', '') for entry in historical_data) if historical_data else None,
            'end': max(entry.get('timestamp', '') for entry in historical_data) if historical_data else None
        },
        'trends': trends,
        'summary': {}
    }
    
    if historical_data:
        # Recent performance summary (last 10 runs)
        recent_runs = historical_data[-10:]
        
        success_rates = [run.get('test_success_rate', 0) for run in recent_runs]
        total_durations = [run.get('total_duration', 0) for run in recent_runs]
        
        dashboard['summary'] = {
            'avg_success_rate': statistics.mean(success_rates) if success_rates else 0,
            'avg_duration': statistics.mean(total_durations) if total_durations else 0,
            'recent_runs': len(recent_runs),
            'stability': 'stable' if all(rate >= 95 for rate in success_rates) else 'unstable'
        }
    
    return dashboard

def create_performance_report(trends, dashboard):
    """Create comprehensive performance report."""
    print(f"\n{'='*60}")
    print("📊 TURBOAPI PERFORMANCE TREND ANALYSIS")
    print(f"{'='*60}")
    
    print(f"📈 Performance Dashboard Summary:")
    print(f"   Total benchmark runs: {dashboard['total_runs']}")
    print(f"   Recent average success rate: {dashboard['summary'].get('avg_success_rate', 0):.1f}%")
    print(f"   Recent average duration: {dashboard['summary'].get('avg_duration', 0):.2f}s")
    print(f"   System stability: {dashboard['summary'].get('stability', 'unknown')}")
    
    if trends:
        print(f"\n📊 Performance Trends:")
        
        for metric, trend_data in trends.items():
            trend_percent = trend_data['trend_percent']
            direction = "📈" if trend_percent > 0 else "📉" if trend_percent < 0 else "➡️"
            
            # Determine if trend is good or bad based on metric
            is_good_trend = False
            if 'success_rate' in metric:
                is_good_trend = trend_percent > 0  # Higher success rate is good
            elif 'duration' in metric:
                is_good_trend = trend_percent < 0  # Lower duration is good
            
            status = "✅" if is_good_trend else "⚠️" if abs(trend_percent) < 10 else "🔴"
            
            print(f"   {status} {metric}: {direction} {trend_percent:+.1f}%")
            print(f"      Recent: {trend_data['recent_avg']:.3f}")
            print(f"      Historical: {trend_data['older_avg']:.3f}")
            print(f"      Data points: {trend_data['data_points']}")
    
    # Performance recommendations
    print(f"\n💡 Performance Recommendations:")
    
    if dashboard['summary'].get('avg_success_rate', 0) < 95:
        print("   🔴 Success rate below 95% - investigate test failures")
    
    if dashboard['summary'].get('avg_duration', 0) > 5:
        print("   🟡 Test duration above 5s - consider optimization")
    
    duration_trend = trends.get('total_duration', {})
    if duration_trend.get('trend_percent', 0) > 20:
        print("   🔴 Test duration increasing significantly - performance regression")
    
    if not trends:
        print("   📊 Collect more benchmark data for trend analysis")
    
    success_trend = trends.get('test_success_rate', {})
    if success_trend.get('trend_percent', 0) < -5:
        print("   🔴 Success rate declining - investigate reliability issues")
    
    print(f"\n🎯 Overall Assessment:")
    
    stability = dashboard['summary'].get('stability', 'unknown')
    avg_success = dashboard['summary'].get('avg_success_rate', 0)
    
    if stability == 'stable' and avg_success >= 95:
        print("   🎉 EXCELLENT: TurboAPI performance is stable and reliable")
    elif stability == 'stable' and avg_success >= 90:
        print("   ✅ GOOD: Performance is stable with minor issues")
    elif avg_success >= 90:
        print("   ⚠️ FAIR: Performance acceptable but stability concerns")
    else:
        print("   🔴 NEEDS ATTENTION: Performance or stability issues detected")

def save_dashboard_data(dashboard):
    """Save dashboard data for web interface."""
    with open('performance_dashboard.json', 'w') as f:
        json.dump(dashboard, f, indent=2)
    
    print(f"💾 Performance dashboard saved to performance_dashboard.json")

def main():
    """Main benchmark comparison function."""
    print("📊 TurboAPI Benchmark Comparison")
    print("=" * 40)
    
    # Load historical data
    historical_data = load_performance_history()
    
    if not historical_data:
        print("⚠️ No historical data available for comparison")
        return 0
    
    print(f"📈 Loaded {len(historical_data)} historical benchmark runs")
    
    # Analyze trends
    trends = analyze_performance_trends(historical_data)
    
    # Generate dashboard
    dashboard = generate_performance_dashboard(historical_data, trends)
    
    # Create report
    create_performance_report(trends, dashboard)
    
    # Save dashboard data
    save_dashboard_data(dashboard)
    
    print(f"\n✅ Benchmark comparison completed")
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
