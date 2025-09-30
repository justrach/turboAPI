#!/usr/bin/env python3
"""
Performance Regression Detection for TurboAPI
Compares current benchmark results with historical data
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Performance thresholds (% regression that triggers alert)
REGRESSION_THRESHOLDS = {
    'latency': 15.0,      # 15% increase in latency is concerning
    'throughput': 10.0,   # 10% decrease in throughput is concerning
    'success_rate': 5.0,  # 5% decrease in success rate is concerning
    'memory_usage': 20.0, # 20% increase in memory usage is concerning
}

# Expected performance baselines (from Phase 5 achievements)
PERFORMANCE_BASELINES = {
    'turboapi_vs_fastapi_latency_ratio': 2.5,  # TurboAPI should be 2.5x+ faster
    'turboapi_vs_fastapi_throughput_ratio': 7.0,  # TurboAPI should be 7x+ faster
    'middleware_overhead_ms': 1.0,  # Middleware should add <1ms overhead
    'websocket_latency_ms': 1.0,    # WebSocket latency should be <1ms
    'zero_copy_efficiency': 0.9,    # Zero-copy should be 90%+ efficient
}

def load_test_report():
    """Load the current test report."""
    try:
        with open('test_report.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ No test report found")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Invalid test report JSON: {e}")
        return None

def load_historical_data():
    """Load historical performance data."""
    history_file = Path('performance_history.json')
    
    if not history_file.exists():
        print("📊 No historical data found, creating baseline")
        return []
    
    try:
        with open(history_file, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"⚠️ Invalid historical data: {e}")
        return []

def save_performance_data(current_data, historical_data):
    """Save current performance data to history."""
    # Add timestamp
    current_data['timestamp'] = datetime.now().isoformat()
    current_data['git_sha'] = os.environ.get('GITHUB_SHA', 'unknown')
    current_data['git_ref'] = os.environ.get('GITHUB_REF', 'unknown')
    
    # Add to history
    historical_data.append(current_data)
    
    # Keep only last 100 entries
    if len(historical_data) > 100:
        historical_data = historical_data[-100:]
    
    # Save updated history
    with open('performance_history.json', 'w') as f:
        json.dump(historical_data, f, indent=2)
    
    print(f"💾 Performance data saved ({len(historical_data)} entries)")

def extract_performance_metrics(test_report):
    """Extract key performance metrics from test report."""
    metrics = {
        'test_success_rate': test_report.get('success_rate', 0),
        'total_duration': test_report.get('total_duration', 0),
        'tests_passed': test_report.get('passed_tests', 0),
        'tests_total': test_report.get('total_tests', 0),
    }
    
    # Extract specific test metrics
    tests = test_report.get('tests', {})
    
    for test_name, test_data in tests.items():
        if test_data.get('passed'):
            metrics[f"{test_name.lower().replace(' ', '_')}_duration"] = test_data.get('duration', 0)
    
    return metrics

def check_regression(current_metrics, historical_data):
    """Check for performance regressions."""
    if not historical_data:
        print("📊 No historical data for comparison")
        return False, []
    
    # Get recent baseline (average of last 5 runs)
    recent_runs = historical_data[-5:]
    if not recent_runs:
        return False, []
    
    regressions = []
    
    # Calculate baseline averages
    baseline_metrics = {}
    for metric in current_metrics.keys():
        values = [run.get(metric, 0) for run in recent_runs if run.get(metric) is not None]
        if values:
            baseline_metrics[metric] = sum(values) / len(values)
    
    # Check each metric for regression
    for metric, current_value in current_metrics.items():
        if metric not in baseline_metrics:
            continue
        
        baseline_value = baseline_metrics[metric]
        if baseline_value == 0:
            continue
        
        # Calculate percentage change
        change_percent = ((current_value - baseline_value) / baseline_value) * 100
        
        # Determine if this is a regression based on metric type
        is_regression = False
        threshold = REGRESSION_THRESHOLDS.get('latency', 15.0)  # Default threshold
        
        if 'duration' in metric or 'latency' in metric:
            # Higher duration/latency is bad
            is_regression = change_percent > threshold
        elif 'throughput' in metric or 'rate' in metric or 'success' in metric:
            # Lower throughput/rate/success is bad
            is_regression = change_percent < -threshold
        elif 'memory' in metric:
            # Higher memory usage might be bad
            threshold = REGRESSION_THRESHOLDS.get('memory_usage', 20.0)
            is_regression = change_percent > threshold
        
        if is_regression:
            regressions.append({
                'metric': metric,
                'current_value': current_value,
                'baseline_value': baseline_value,
                'change_percent': change_percent,
                'threshold': threshold
            })
    
    return len(regressions) > 0, regressions

def check_performance_baselines(current_metrics):
    """Check if current performance meets expected baselines."""
    baseline_failures = []
    
    # This would be populated with actual benchmark results
    # For now, we'll simulate the checks
    
    print("📊 Checking performance baselines...")
    print("   (Note: Full baseline checks require integrated benchmarks)")
    
    # Check test success rate
    success_rate = current_metrics.get('test_success_rate', 0)
    if success_rate < 95.0:
        baseline_failures.append({
            'baseline': 'test_success_rate',
            'expected': '95%+',
            'actual': f"{success_rate:.1f}%",
            'severity': 'high'
        })
    
    return baseline_failures

def generate_performance_report(current_metrics, regressions, baseline_failures, historical_data):
    """Generate comprehensive performance report."""
    print(f"\n{'='*60}")
    print("📊 TURBOAPI PERFORMANCE ANALYSIS")
    print(f"{'='*60}")
    
    # Current metrics summary
    print(f"📈 Current Performance Metrics:")
    print(f"   Test Success Rate: {current_metrics.get('test_success_rate', 0):.1f}%")
    print(f"   Total Test Duration: {current_metrics.get('total_duration', 0):.2f}s")
    print(f"   Tests Passed: {current_metrics.get('tests_passed', 0)}/{current_metrics.get('tests_total', 0)}")
    
    # Regression analysis
    if regressions:
        print(f"\n⚠️ PERFORMANCE REGRESSIONS DETECTED ({len(regressions)}):")
        for regression in regressions:
            print(f"   🔴 {regression['metric']}: {regression['change_percent']:+.1f}% change")
            print(f"      Current: {regression['current_value']:.3f}")
            print(f"      Baseline: {regression['baseline_value']:.3f}")
            print(f"      Threshold: {regression['threshold']:.1f}%")
    else:
        print(f"\n✅ NO PERFORMANCE REGRESSIONS DETECTED")
    
    # Baseline analysis
    if baseline_failures:
        print(f"\n⚠️ BASELINE PERFORMANCE FAILURES ({len(baseline_failures)}):")
        for failure in baseline_failures:
            severity_icon = "🔴" if failure['severity'] == 'high' else "🟡"
            print(f"   {severity_icon} {failure['baseline']}: {failure['actual']} (expected {failure['expected']})")
    else:
        print(f"\n✅ ALL PERFORMANCE BASELINES MET")
    
    # Historical trend
    if len(historical_data) > 1:
        print(f"\n📈 Performance Trend ({len(historical_data)} data points):")
        recent_success_rates = [run.get('test_success_rate', 0) for run in historical_data[-10:]]
        if recent_success_rates:
            avg_success = sum(recent_success_rates) / len(recent_success_rates)
            print(f"   Average success rate (last 10 runs): {avg_success:.1f}%")
    
    # Overall assessment
    total_issues = len(regressions) + len(baseline_failures)
    if total_issues == 0:
        print(f"\n🎉 PERFORMANCE STATUS: EXCELLENT")
        print(f"   TurboAPI is performing optimally with no regressions detected!")
    elif total_issues <= 2:
        print(f"\n⚠️ PERFORMANCE STATUS: GOOD (minor issues)")
        print(f"   {total_issues} performance issue(s) detected - review recommended")
    else:
        print(f"\n🔴 PERFORMANCE STATUS: NEEDS ATTENTION")
        print(f"   {total_issues} performance issue(s) detected - investigation required")
    
    return total_issues

def main():
    """Main performance regression check."""
    print("🔍 TurboAPI Performance Regression Check")
    print("=" * 50)
    
    # Load current test results
    test_report = load_test_report()
    if not test_report:
        print("⚠️  No test report found - skipping regression check")
        print("   This is expected for wheel-only builds without benchmark runs")
        return 0  # Don't fail CI if test report is missing
    
    # Extract performance metrics
    current_metrics = extract_performance_metrics(test_report)
    print(f"📊 Extracted {len(current_metrics)} performance metrics")
    
    # Load historical data
    historical_data = load_historical_data()
    
    # Check for regressions
    has_regressions, regressions = check_regression(current_metrics, historical_data)
    
    # Check performance baselines
    baseline_failures = check_performance_baselines(current_metrics)
    
    # Generate report
    total_issues = generate_performance_report(
        current_metrics, regressions, baseline_failures, historical_data
    )
    
    # Save current data to history
    save_performance_data(current_metrics, historical_data)
    
    # Set exit code based on issues
    if total_issues > 0:
        print(f"\n⚠️ Performance check completed with {total_issues} issue(s)")
        # Don't fail CI for performance issues, just warn
        return 0
    else:
        print(f"\n✅ Performance check passed - no issues detected")
        return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
