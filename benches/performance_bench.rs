use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::runtime::Runtime;
use tokio::sync::Semaphore;

/// Comprehensive benchmark suite for TurboAPI performance validation
/// Tests all critical paths: routing, JSON, async, concurrency

// ============================================================================
// ROUTE KEY CREATION BENCHMARKS
// ============================================================================

fn bench_route_key_creation(c: &mut Criterion) {
    let mut group = c.benchmark_group("route_key");

    // Test different path lengths
    let paths = [
        ("/", "root"),
        ("/api/users", "short"),
        ("/api/v1/users/123/posts", "medium"),
        ("/api/v1/organizations/abc-def-123/projects/xyz-789/tasks/456/comments", "long"),
    ];

    for (path, name) in paths.iter() {
        group.bench_with_input(BenchmarkId::new("heap_alloc", name), path, |b, path| {
            b.iter(|| {
                let method = black_box("GET");
                let _route_key = black_box(format!("{} {}", method, path));
            });
        });

        group.bench_with_input(BenchmarkId::new("stack_buffer", name), path, |b, path| {
            b.iter(|| {
                let method = black_box("GET");
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

                let _route_key = black_box(unsafe {
                    String::from_utf8_unchecked(buffer[..pos].to_vec())
                });
            });
        });
    }

    group.finish();
}

// ============================================================================
// JSON SERIALIZATION BENCHMARKS (serde_json vs simd-json)
// ============================================================================

fn bench_json_serialization(c: &mut Criterion) {
    use serde_json::json;

    let mut group = c.benchmark_group("json_serialize");

    // Small response (typical API response)
    let small_json = json!({
        "status": "success",
        "message": "Hello World",
        "id": 12345
    });

    // Medium response (list with metadata)
    let medium_json = json!({
        "data": (0..20).map(|i| {
            json!({
                "id": i,
                "name": format!("Item {}", i),
                "active": i % 2 == 0
            })
        }).collect::<Vec<_>>(),
        "total": 20,
        "page": 1
    });

    // Large response (complex nested structure)
    let large_json = json!({
        "users": (0..100).map(|i| {
            json!({
                "id": i,
                "name": format!("User {}", i),
                "email": format!("user{}@example.com", i),
                "profile": {
                    "bio": "Lorem ipsum dolor sit amet",
                    "avatar": format!("https://example.com/avatar/{}.png", i),
                    "settings": {
                        "theme": "dark",
                        "notifications": true,
                        "language": "en"
                    }
                },
                "posts": (0..5).map(|j| {
                    json!({
                        "id": j,
                        "title": format!("Post {} by User {}", j, i),
                        "likes": j * 10
                    })
                }).collect::<Vec<_>>()
            })
        }).collect::<Vec<_>>(),
        "metadata": {
            "timestamp": 1695734400,
            "version": "2.0",
            "total_users": 100
        }
    });

    // Benchmark serde_json
    group.bench_function("serde_small", |b| {
        b.iter(|| {
            let _s = black_box(serde_json::to_string(&small_json).unwrap());
        });
    });

    group.bench_function("serde_medium", |b| {
        b.iter(|| {
            let _s = black_box(serde_json::to_string(&medium_json).unwrap());
        });
    });

    group.bench_function("serde_large", |b| {
        b.iter(|| {
            let _s = black_box(serde_json::to_string(&large_json).unwrap());
        });
    });

    // Benchmark simd-json serialization (from pre-serialized bytes)
    let small_bytes = serde_json::to_vec(&small_json).unwrap();
    let medium_bytes = serde_json::to_vec(&medium_json).unwrap();
    let large_bytes = serde_json::to_vec(&large_json).unwrap();

    group.throughput(Throughput::Bytes(small_bytes.len() as u64));
    group.bench_function("simd_parse_small", |b| {
        b.iter(|| {
            let mut bytes = small_bytes.clone();
            let _parsed: simd_json::OwnedValue = black_box(
                simd_json::to_owned_value(&mut bytes).unwrap()
            );
        });
    });

    group.throughput(Throughput::Bytes(medium_bytes.len() as u64));
    group.bench_function("simd_parse_medium", |b| {
        b.iter(|| {
            let mut bytes = medium_bytes.clone();
            let _parsed: simd_json::OwnedValue = black_box(
                simd_json::to_owned_value(&mut bytes).unwrap()
            );
        });
    });

    group.throughput(Throughput::Bytes(large_bytes.len() as u64));
    group.bench_function("simd_parse_large", |b| {
        b.iter(|| {
            let mut bytes = large_bytes.clone();
            let _parsed: simd_json::OwnedValue = black_box(
                simd_json::to_owned_value(&mut bytes).unwrap()
            );
        });
    });

    group.finish();
}

// ============================================================================
// ASYNC RUNTIME BENCHMARKS
// ============================================================================

fn bench_async_task_spawning(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();

    let mut group = c.benchmark_group("async_tasks");
    group.measurement_time(Duration::from_secs(5));

    // Benchmark task spawn overhead
    group.bench_function("spawn_single", |b| {
        b.iter(|| {
            rt.block_on(async {
                let handle = tokio::spawn(async {
                    black_box(42)
                });
                black_box(handle.await.unwrap())
            })
        });
    });

    // Benchmark concurrent task spawning
    for count in [10, 50, 100, 500, 1000].iter() {
        group.bench_with_input(
            BenchmarkId::new("spawn_concurrent", count),
            count,
            |b, &count| {
                b.iter(|| {
                    rt.block_on(async {
                        let tasks: Vec<_> = (0..count)
                            .map(|i| {
                                tokio::spawn(async move {
                                    black_box(i * 2)
                                })
                            })
                            .collect();

                        for task in tasks {
                            black_box(task.await.unwrap());
                        }
                    })
                });
            },
        );
    }

    group.finish();
}

// ============================================================================
// SEMAPHORE (RATE LIMITING) BENCHMARKS
// ============================================================================

fn bench_semaphore_overhead(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();

    let mut group = c.benchmark_group("semaphore");

    // Different semaphore capacities
    for capacity in [100, 1000, 10000, 100000].iter() {
        let semaphore = Arc::new(Semaphore::new(*capacity));

        group.bench_with_input(
            BenchmarkId::new("acquire_release", capacity),
            &semaphore,
            |b, semaphore| {
                b.iter(|| {
                    rt.block_on(async {
                        let permit = semaphore.acquire().await.unwrap();
                        black_box(&permit);
                        drop(permit);
                    })
                });
            },
        );
    }

    // Benchmark concurrent semaphore access
    let semaphore = Arc::new(Semaphore::new(1000));
    for concurrent in [10, 50, 100, 200].iter() {
        group.bench_with_input(
            BenchmarkId::new("concurrent_acquire", concurrent),
            concurrent,
            |b, &concurrent| {
                b.iter(|| {
                    rt.block_on(async {
                        let sem = Arc::clone(&semaphore);
                        let tasks: Vec<_> = (0..concurrent)
                            .map(|_| {
                                let sem = Arc::clone(&sem);
                                tokio::spawn(async move {
                                    let permit = sem.acquire().await.unwrap();
                                    black_box(&permit);
                                    drop(permit);
                                })
                            })
                            .collect();

                        for task in tasks {
                            task.await.unwrap();
                        }
                    })
                });
            },
        );
    }

    group.finish();
}

// ============================================================================
// QUERY STRING PARSING BENCHMARKS
// ============================================================================

fn bench_query_string_parsing(c: &mut Criterion) {
    let mut group = c.benchmark_group("query_parsing");

    let queries = [
        ("", "empty"),
        ("id=123", "single"),
        ("id=123&name=test&active=true", "small"),
        ("id=123&name=John%20Doe&email=test%40example.com&page=1&limit=20&sort=created_at&order=desc", "medium"),
        ("a=1&b=2&c=3&d=4&e=5&f=6&g=7&h=8&i=9&j=10&k=11&l=12&m=13&n=14&o=15&p=16&q=17&r=18&s=19&t=20", "many_params"),
    ];

    for (query, name) in queries.iter() {
        group.bench_with_input(BenchmarkId::new("parse", name), query, |b, query| {
            b.iter(|| {
                let mut params: HashMap<String, String> = HashMap::new();
                for pair in query.split('&') {
                    if pair.is_empty() {
                        continue;
                    }
                    if let Some((key, value)) = pair.split_once('=') {
                        params.insert(
                            black_box(key.to_string()),
                            black_box(value.to_string()),
                        );
                    }
                }
                black_box(params)
            });
        });

        // With URL decoding
        group.bench_with_input(BenchmarkId::new("parse_decode", name), query, |b, query| {
            b.iter(|| {
                let mut params: HashMap<String, String> = HashMap::new();
                for pair in query.split('&') {
                    if pair.is_empty() {
                        continue;
                    }
                    if let Some((key, value)) = pair.split_once('=') {
                        // Simple URL decode simulation
                        let decoded = value.replace("%20", " ").replace("%40", "@");
                        params.insert(
                            black_box(key.to_string()),
                            black_box(decoded),
                        );
                    }
                }
                black_box(params)
            });
        });
    }

    group.finish();
}

// ============================================================================
// PATH PARAMETER EXTRACTION BENCHMARKS
// ============================================================================

fn bench_path_param_extraction(c: &mut Criterion) {
    let mut group = c.benchmark_group("path_params");

    let test_cases = [
        ("/users/{id}", "/users/12345", "single"),
        ("/users/{user_id}/posts/{post_id}", "/users/123/posts/456", "double"),
        ("/org/{org}/proj/{proj}/task/{task}/comment/{comment}", "/org/abc/proj/def/task/123/comment/789", "many"),
    ];

    for (pattern, path, name) in test_cases.iter() {
        group.bench_with_input(BenchmarkId::new("extract", name), &(pattern, path), |b, (pattern, path)| {
            b.iter(|| {
                let pattern_parts: Vec<&str> = pattern.split('/').collect();
                let path_parts: Vec<&str> = path.split('/').collect();

                let mut params: HashMap<String, String> = HashMap::new();

                for (p_part, path_part) in pattern_parts.iter().zip(path_parts.iter()) {
                    if p_part.starts_with('{') && p_part.ends_with('}') {
                        let param_name = &p_part[1..p_part.len()-1];
                        params.insert(
                            black_box(param_name.to_string()),
                            black_box(path_part.to_string()),
                        );
                    }
                }

                black_box(params)
            });
        });
    }

    group.finish();
}

// ============================================================================
// HANDLER DISPATCH SIMULATION BENCHMARKS
// ============================================================================

fn bench_handler_dispatch(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();

    let mut group = c.benchmark_group("handler_dispatch");
    group.measurement_time(Duration::from_secs(5));

    // Simulate sync handler (direct call)
    group.bench_function("sync_direct", |b| {
        b.iter(|| {
            // Simulate sync handler work
            let result = {
                let data = black_box(vec![1, 2, 3, 4, 5]);
                let sum: i32 = data.iter().sum();
                format!(r#"{{"result": {}}}"#, sum)
            };
            black_box(result)
        });
    });

    // Simulate async handler (with tokio spawn)
    group.bench_function("async_spawn", |b| {
        b.iter(|| {
            rt.block_on(async {
                let handle = tokio::spawn(async {
                    let data = black_box(vec![1, 2, 3, 4, 5]);
                    let sum: i32 = data.iter().sum();
                    format!(r#"{{"result": {}}}"#, sum)
                });
                black_box(handle.await.unwrap())
            })
        });
    });

    // Simulate async handler with semaphore (rate limiting)
    let semaphore = Arc::new(Semaphore::new(10000));
    group.bench_function("async_with_semaphore", |b| {
        b.iter(|| {
            rt.block_on(async {
                let permit = semaphore.acquire().await.unwrap();
                let result = {
                    let data = black_box(vec![1, 2, 3, 4, 5]);
                    let sum: i32 = data.iter().sum();
                    format!(r#"{{"result": {}}}"#, sum)
                };
                drop(permit);
                black_box(result)
            })
        });
    });

    group.finish();
}

// ============================================================================
// CONCURRENT REQUEST SIMULATION
// ============================================================================

fn bench_concurrent_requests(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();

    let mut group = c.benchmark_group("concurrent_requests");
    group.measurement_time(Duration::from_secs(10));
    group.sample_size(50);

    for thread_count in [10, 50, 100, 200, 500].iter() {
        group.throughput(Throughput::Elements(*thread_count as u64));
        group.bench_with_input(
            BenchmarkId::new("tokio_spawn", thread_count),
            thread_count,
            |b, &thread_count| {
                b.iter(|| {
                    rt.block_on(async {
                        let tasks: Vec<_> = (0..thread_count)
                            .map(|i| {
                                tokio::spawn(async move {
                                    // Simulate request processing
                                    let route_key = format!("GET /api/users/{}", i);
                                    let response = format!(r#"{{"id": {}, "status": "ok"}}"#, i);
                                    black_box((route_key, response))
                                })
                            })
                            .collect();

                        for task in tasks {
                            black_box(task.await.unwrap());
                        }
                    });
                });
            },
        );
    }

    // With semaphore rate limiting
    let semaphore = Arc::new(Semaphore::new(100));
    for thread_count in [50, 100, 200].iter() {
        group.bench_with_input(
            BenchmarkId::new("with_rate_limit", thread_count),
            thread_count,
            |b, &thread_count| {
                b.iter(|| {
                    rt.block_on(async {
                        let tasks: Vec<_> = (0..thread_count)
                            .map(|i| {
                                let sem = Arc::clone(&semaphore);
                                tokio::spawn(async move {
                                    let _permit = sem.acquire().await.unwrap();
                                    // Simulate request processing
                                    let route_key = format!("GET /api/users/{}", i);
                                    let response = format!(r#"{{"id": {}, "status": "ok"}}"#, i);
                                    black_box((route_key, response))
                                })
                            })
                            .collect();

                        for task in tasks {
                            black_box(task.await.unwrap());
                        }
                    });
                });
            },
        );
    }

    group.finish();
}

// ============================================================================
// BYTES HANDLING BENCHMARKS
// ============================================================================

fn bench_bytes_handling(c: &mut Criterion) {
    use bytes::Bytes;

    let mut group = c.benchmark_group("bytes");

    let sizes = [64, 256, 1024, 4096, 16384];

    for size in sizes.iter() {
        let data: Vec<u8> = (0..*size).map(|i| (i % 256) as u8).collect();
        let bytes = Bytes::from(data.clone());

        group.throughput(Throughput::Bytes(*size as u64));

        group.bench_with_input(BenchmarkId::new("clone", size), &bytes, |b, bytes| {
            b.iter(|| {
                black_box(bytes.clone())
            });
        });

        group.bench_with_input(BenchmarkId::new("slice", size), &bytes, |b, bytes| {
            b.iter(|| {
                let mid = bytes.len() / 2;
                black_box(bytes.slice(0..mid))
            });
        });
    }

    group.finish();
}

criterion_group!(
    benches,
    bench_route_key_creation,
    bench_json_serialization,
    bench_async_task_spawning,
    bench_semaphore_overhead,
    bench_query_string_parsing,
    bench_path_param_extraction,
    bench_handler_dispatch,
    bench_concurrent_requests,
    bench_bytes_handling
);

criterion_main!(benches);
