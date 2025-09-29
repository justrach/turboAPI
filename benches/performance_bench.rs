use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};
use tokio::runtime::Runtime;
use std::time::Duration;

/// Benchmark suite for TurboAPI performance validation
/// Mirrors the Python benchmarks for cross-language validation

fn bench_route_key_creation(c: &mut Criterion) {
    c.bench_function("route_key_creation", |b| {
        b.iter(|| {
            // Test our optimized route key creation
            let method = black_box("GET");
            let path = black_box("/api/v1/users/123/posts");
            
            // Simulate our zero-allocation route key creation
            let mut buffer = [0u8; 256];
            let method_bytes = method.as_bytes();
            let path_bytes = path.as_bytes();
            
            let mut pos = 0;
            for &byte in method_bytes {
                buffer[pos] = byte;
                pos += 1;
            }
            buffer[pos] = b' ';
            pos += 1;
            for &byte in path_bytes {
                buffer[pos] = byte;
                pos += 1;
            }
            
            let _route_key = black_box(String::from_utf8_lossy(&buffer[..pos]));
        });
    });
}

fn bench_string_allocation_comparison(c: &mut Criterion) {
    let mut group = c.benchmark_group("string_allocation");
    
    group.bench_function("heap_allocation", |b| {
        b.iter(|| {
            let method = black_box("GET");
            let path = black_box("/api/v1/users/123/posts");
            let _route_key = black_box(format!("{} {}", method, path));
        });
    });
    
    group.bench_function("stack_buffer", |b| {
        b.iter(|| {
            let method = black_box("GET");
            let path = black_box("/api/v1/users/123/posts");
            
            let mut buffer = [0u8; 256];
            let method_bytes = method.as_bytes();
            let path_bytes = path.as_bytes();
            
            let mut pos = 0;
            for &byte in method_bytes {
                buffer[pos] = byte;
                pos += 1;
            }
            buffer[pos] = b' ';
            pos += 1;
            for &byte in path_bytes {
                buffer[pos] = byte;
                pos += 1;
            }
            
            let _route_key = black_box(String::from_utf8_lossy(&buffer[..pos]));
        });
    });
    
    group.finish();
}

fn bench_concurrent_requests(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();
    
    let mut group = c.benchmark_group("concurrent_requests");
    group.measurement_time(Duration::from_secs(10));
    
    for thread_count in [10, 50, 100, 200].iter() {
        group.bench_with_input(
            BenchmarkId::new("threads", thread_count),
            thread_count,
            |b, &thread_count| {
                b.iter(|| {
                    rt.block_on(async {
                        // Simulate concurrent request processing
                        let tasks: Vec<_> = (0..thread_count)
                            .map(|_| {
                                tokio::spawn(async {
                                    // Simulate request processing overhead
                                    let _processing = black_box(format!("Processing request"));
                                    tokio::time::sleep(Duration::from_micros(100)).await;
                                })
                            })
                            .collect();
                        
                        for task in tasks {
                            let _ = task.await;
                        }
                    });
                });
            },
        );
    }
    group.finish();
}

#[allow(dead_code)]
fn bench_memory_allocation(c: &mut Criterion) {
    c.bench_function("route_key_creation", |b| {
        b.iter(|| {
            // Test our optimized route key creation
            let method = black_box("GET");
            let path = black_box("/api/v1/users/123/posts");
            
            // Simulate our zero-allocation route key creation
            let mut buffer = [0u8; 256];
            let method_bytes = method.as_bytes();
            let path_bytes = path.as_bytes();
            
            let mut pos = 0;
            for &byte in method_bytes {
                buffer[pos] = byte;
                pos += 1;
            }
            buffer[pos] = b' ';
            pos += 1;
            for &byte in path_bytes {
                buffer[pos] = byte;
                pos += 1;
            }
            
            let _route_key = black_box(String::from_utf8_lossy(&buffer[..pos]));
        });
    });
}

fn bench_json_serialization(c: &mut Criterion) {
    use serde_json::json;
    
    let mut group = c.benchmark_group("json_serialization");
    
    let small_json = json!({
        "status": "success",
        "message": "Hello World"
    });
    
    let large_json = json!({
        "data": (0..100).collect::<Vec<i32>>(),
        "metadata": {
            "timestamp": 1695734400,
            "version": "2.0",
            "processed": (0..50).map(|i| i * i).collect::<Vec<i32>>()
        },
        "status": "success"
    });
    
    group.bench_function("small_json", |b| {
        b.iter(|| {
            let _serialized = black_box(serde_json::to_string(&small_json).unwrap());
        });
    });
    
    group.bench_function("large_json", |b| {
        b.iter(|| {
            let _serialized = black_box(serde_json::to_string(&large_json).unwrap());
        });
    });
    
    group.finish();
}

criterion_group!(
    benches,
    bench_route_key_creation,
    bench_string_allocation_comparison,
    bench_concurrent_requests,
    bench_json_serialization
);

criterion_main!(benches);
