use pyo3::prelude::*;
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};
use tokio_tungstenite::{
    accept_async, tungstenite::protocol::Message, WebSocketStream,
};
use tokio::net::{TcpListener, TcpStream};
use futures_util::{SinkExt, StreamExt};
use bytes::Bytes;
use serde_json;

type ConnectionId = u64;
type WebSocketSender = tokio::sync::mpsc::UnboundedSender<Message>;

/// WebSocket Server with real-time capabilities
#[pyclass]
pub struct WebSocketServer {
    connections: Arc<RwLock<HashMap<ConnectionId, WebSocketSender>>>,
    message_handlers: Arc<Mutex<HashMap<String, Arc<pyo3::Py<pyo3::PyAny>>>>>,
    host: String,
    port: u16,
    next_connection_id: Arc<Mutex<ConnectionId>>,
}

#[pymethods]
impl WebSocketServer {
    #[new]
    pub fn new(host: Option<String>, port: Option<u16>) -> Self {
        WebSocketServer {
            connections: Arc::new(RwLock::new(HashMap::new())),
            message_handlers: Arc::new(Mutex::new(HashMap::new())),
            host: host.unwrap_or_else(|| "127.0.0.1".to_string()),
            port: port.unwrap_or(8080),
            next_connection_id: Arc::new(Mutex::new(1)),
        }
    }

    /// Register a message handler for specific message types
    pub fn add_handler(&mut self, message_type: String, handler: PyObject) -> PyResult<()> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let handlers = Arc::clone(&self.message_handlers);
        
        rt.block_on(async {
            let mut handlers_guard = handlers.lock().await;
            handlers_guard.insert(message_type, Arc::new(handler));
            Ok(())
        })
    }

    /// Start the WebSocket server
    pub fn run(&self, py: Python) -> PyResult<()> {
        let addr: SocketAddr = format!("{}:{}", self.host, self.port)
            .parse()
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid address: {}", e)))?;

        let connections = Arc::clone(&self.connections);
        let handlers = Arc::clone(&self.message_handlers);
        let next_id = Arc::clone(&self.next_connection_id);
        
        py.allow_threads(|| {
            // Create multi-threaded Tokio runtime for WebSockets
            let worker_threads = std::thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(4);
            
            let rt = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(worker_threads)
                .enable_all()
                .build()
                .unwrap();
            
            rt.block_on(async {
                let listener = TcpListener::bind(addr).await.unwrap();
                // Production WebSocket server - minimal startup logging
                if cfg!(debug_assertions) {
                    println!("🌐 TurboAPI WebSocket server starting on ws://{}", addr);
                    println!("🧵 Using {} worker threads for real-time processing", worker_threads);
                    println!("⚡ Features: Bidirectional streaming, broadcast, multiplexing");
                }

                loop {
                    let (stream, client_addr) = listener.accept().await.unwrap();
                    let connections_clone = Arc::clone(&connections);
                    let handlers_clone = Arc::clone(&handlers);
                    let next_id_clone = Arc::clone(&next_id);

                    // Spawn each WebSocket connection
                    tokio::task::spawn(async move {
                        if let Err(e) = handle_websocket_connection(
                            stream,
                            client_addr,
                            connections_clone,
                            handlers_clone,
                            next_id_clone,
                        ).await {
                            eprintln!("WebSocket connection error: {:?}", e);
                        }
                    });
                }
            })
        });

        Ok(())
    }

    /// Broadcast a message to all connected clients
    pub fn broadcast(&self, message: String) -> PyResult<usize> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let connections = Arc::clone(&self.connections);
        
        rt.block_on(async {
            let connections_guard = connections.read().await;
            let mut sent_count = 0;
            
            for sender in connections_guard.values() {
                if sender.send(Message::Text(message.clone())).is_ok() {
                    sent_count += 1;
                }
            }
            
            Ok(sent_count)
        })
    }

    /// Send a message to a specific connection
    pub fn send_to(&self, connection_id: u64, message: String) -> PyResult<bool> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let connections = Arc::clone(&self.connections);
        
        rt.block_on(async {
            let connections_guard = connections.read().await;
            
            if let Some(sender) = connections_guard.get(&connection_id) {
                Ok(sender.send(Message::Text(message)).is_ok())
            } else {
                Ok(false)
            }
        })
    }

    /// Get the number of active connections
    pub fn connection_count(&self) -> usize {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let connections = Arc::clone(&self.connections);
        
        rt.block_on(async {
            let connections_guard = connections.read().await;
            connections_guard.len()
        })
    }

    /// Get server info
    pub fn info(&self) -> String {
        format!(
            "WebSocket Server on {}:{} ({} connections)",
            self.host, 
            self.port,
            self.connection_count()
        )
    }
}

/// WebSocket Connection wrapper for Python
#[pyclass]
pub struct WebSocketConnection {
    connection_id: ConnectionId,
    sender: Option<WebSocketSender>,
    is_connected: bool,
}

#[pymethods]
impl WebSocketConnection {
    #[new]
    pub fn new(connection_id: u64) -> Self {
        WebSocketConnection {
            connection_id,
            sender: None,
            is_connected: false,
        }
    }

    /// Send a text message
    pub fn send_text(&mut self, message: String) -> PyResult<bool> {
        if let Some(ref sender) = self.sender {
            Ok(sender.send(Message::Text(message)).is_ok())
        } else {
            Ok(false)
        }
    }

    /// Send binary data
    pub fn send_binary(&mut self, data: Vec<u8>) -> PyResult<bool> {
        if let Some(ref sender) = self.sender {
            Ok(sender.send(Message::Binary(data)).is_ok())
        } else {
            Ok(false)
        }
    }

    /// Send JSON data
    pub fn send_json(&mut self, data: PyObject) -> PyResult<bool> {
        // Convert Python object to JSON string
        let json_str = Python::with_gil(|py| {
            let json_module = py.import("json")?;
            let data_bound = data.bind(py);
            let json_str = json_module.call_method1("dumps", (data_bound,))?;
            json_str.extract::<String>()
        })?;

        self.send_text(json_str)
    }

    /// Close the connection
    pub fn close(&mut self) -> PyResult<bool> {
        if let Some(ref sender) = self.sender {
            self.is_connected = false;
            Ok(sender.send(Message::Close(None)).is_ok())
        } else {
            Ok(false)
        }
    }

    /// Check if connection is active
    pub fn is_connected(&self) -> bool {
        self.is_connected
    }

    /// Get connection ID
    pub fn connection_id(&self) -> u64 {
        self.connection_id
    }
}

/// WebSocket Message wrapper for Python
#[pyclass]
pub struct WebSocketMessage {
    message_type: String,
    content: String,
    binary_data: Option<Vec<u8>>,
    connection_id: ConnectionId,
}

#[pymethods]
impl WebSocketMessage {
    #[new]
    pub fn new(
        message_type: String,
        content: String,
        connection_id: u64,
        binary_data: Option<Vec<u8>>,
    ) -> Self {
        WebSocketMessage {
            message_type,
            content,
            binary_data,
            connection_id,
        }
    }

    /// Get message type (text, binary, close, ping, pong)
    pub fn message_type(&self) -> String {
        self.message_type.clone()
    }

    /// Get text content
    pub fn text(&self) -> String {
        self.content.clone()
    }

    /// Get binary data
    pub fn binary(&self) -> Option<Vec<u8>> {
        self.binary_data.clone()
    }

    /// Get connection ID
    pub fn connection_id(&self) -> u64 {
        self.connection_id
    }

    /// Parse JSON content
    pub fn json(&self, py: Python) -> PyResult<PyObject> {
        let json_module = py.import("json")?;
        let parsed = json_module.call_method1("loads", (&self.content,))?;
        Ok(parsed.unbind())
    }

    /// Get message size
    pub fn size(&self) -> usize {
        match &self.binary_data {
            Some(data) => data.len(),
            None => self.content.len(),
        }
    }
}

/// Handle individual WebSocket connections
async fn handle_websocket_connection(
    stream: TcpStream,
    client_addr: SocketAddr,
    connections: Arc<RwLock<HashMap<ConnectionId, WebSocketSender>>>,
    _handlers: Arc<Mutex<HashMap<String, Arc<pyo3::Py<pyo3::PyAny>>>>>,
    next_id: Arc<Mutex<ConnectionId>>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // Get unique connection ID
    let connection_id = {
        let mut id_guard = next_id.lock().await;
        let id = *id_guard;
        *id_guard += 1;
        id
    };

    // Only log connections in debug mode
    if cfg!(debug_assertions) {
        println!("🔗 New WebSocket connection: {} (ID: {})", client_addr, connection_id);
    }

    // Accept WebSocket handshake
    let ws_stream = accept_async(stream).await?;
    let (mut ws_sender, mut ws_receiver) = ws_stream.split();

    // Create message channel for this connection
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<Message>();

    // Add connection to the map
    {
        let mut connections_guard = connections.write().await;
        connections_guard.insert(connection_id, tx);
    }

    // Spawn task to handle outgoing messages
    let ws_sender_task = tokio::task::spawn(async move {
        while let Some(message) = rx.recv().await {
            if ws_sender.send(message).await.is_err() {
                break;
            }
        }
    });

    // Handle incoming messages
    let connections_for_cleanup = Arc::clone(&connections);
    let message_handler = tokio::task::spawn(async move {
        while let Some(message) = ws_receiver.next().await {
            match message {
                Ok(Message::Text(text)) => {
                    // Debug logging only
                    if cfg!(debug_assertions) {
                        println!("📨 Received text from {}: {}", connection_id, text);
                    }
                    
                    // Echo the message back (for now)
                    // TODO: Route to Python handlers
                    let echo_response = format!("Echo: {}", text);
                    
                    // Send echo back through the connection
                    let connections_guard = connections_for_cleanup.read().await;
                    if let Some(sender) = connections_guard.get(&connection_id) {
                        let _ = sender.send(Message::Text(echo_response));
                    }
                }
                Ok(Message::Binary(data)) => {
                    // Debug logging only
                    if cfg!(debug_assertions) {
                        println!("📦 Received binary from {}: {} bytes", connection_id, data.len());
                    }
                    
                    // Echo binary data back
                    let connections_guard = connections_for_cleanup.read().await;
                    if let Some(sender) = connections_guard.get(&connection_id) {
                        let _ = sender.send(Message::Binary(data));
                    }
                }
                Ok(Message::Close(_)) => {
                    println!("👋 Connection {} closed", connection_id);
                    break;
                }
                Ok(Message::Ping(data)) => {
                    // Respond to ping with pong
                    let connections_guard = connections_for_cleanup.read().await;
                    if let Some(sender) = connections_guard.get(&connection_id) {
                        let _ = sender.send(Message::Pong(data));
                    }
                }
                Ok(Message::Pong(_)) => {
                    // Handle pong (heartbeat response)
                }
                Ok(Message::Frame(_)) => {
                    // Handle raw frame (usually not needed at application level)
                }
                Err(e) => {
                    eprintln!("WebSocket error for connection {}: {:?}", connection_id, e);
                    break;
                }
            }
        }
    });

    // Wait for either task to complete
    tokio::select! {
        _ = ws_sender_task => {},
        _ = message_handler => {},
    }

    // Clean up connection
    {
        let mut connections_guard = connections.write().await;
        connections_guard.remove(&connection_id);
    }

    println!("🧹 Cleaned up connection {}", connection_id);
    Ok(())
}

/// WebSocket Broadcast Manager for efficient message distribution
#[pyclass]
pub struct BroadcastManager {
    channels: Arc<RwLock<HashMap<String, Vec<WebSocketSender>>>>,
}

#[pymethods]
impl BroadcastManager {
    #[new]
    pub fn new() -> Self {
        BroadcastManager {
            channels: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Create a broadcast channel
    pub fn create_channel(&self, channel_name: String) -> PyResult<()> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let channels = Arc::clone(&self.channels);
        
        rt.block_on(async {
            let mut channels_guard = channels.write().await;
            channels_guard.insert(channel_name, Vec::new());
            Ok(())
        })
    }

    /// Broadcast to a specific channel
    pub fn broadcast_to_channel(&self, channel_name: String, message: String) -> PyResult<usize> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let channels = Arc::clone(&self.channels);
        
        rt.block_on(async {
            let channels_guard = channels.read().await;
            let mut sent_count = 0;
            
            if let Some(senders) = channels_guard.get(&channel_name) {
                for sender in senders {
                    if sender.send(Message::Text(message.clone())).is_ok() {
                        sent_count += 1;
                    }
                }
            }
            
            Ok(sent_count)
        })
    }

    /// Get channel statistics
    pub fn channel_stats(&self) -> PyResult<String> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let channels = Arc::clone(&self.channels);
        
        rt.block_on(async {
            let channels_guard = channels.read().await;
            let mut stats = Vec::new();
            
            for (name, senders) in channels_guard.iter() {
                stats.push(format!("{}: {} connections", name, senders.len()));
            }
            
            Ok(format!("Channels: [{}]", stats.join(", ")))
        })
    }
}
