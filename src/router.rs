use std::collections::HashMap;
use std::sync::Arc;

/// A high-performance radix trie router for path matching and parameter extraction
#[derive(Debug, Clone)]
pub struct RadixRouter {
    root: Arc<RouteNode>,
}

#[derive(Debug, Clone)]
struct RouteNode {
    /// Static path segment (e.g., "users")
    segment: String,
    /// Whether this is a parameter node (e.g., "{id}")
    is_param: bool,
    /// Parameter name if is_param is true
    param_name: Option<String>,
    /// Handler for this exact path
    handler: Option<String>, // Route key like "GET /users/{id}"
    /// Child nodes
    children: HashMap<String, Arc<RouteNode>>,
    /// Wildcard child for parameters
    param_child: Option<Arc<RouteNode>>,
    /// Catch-all child for /*path patterns
    wildcard_child: Option<Arc<RouteNode>>,
}

impl RouteNode {
    fn new(segment: String) -> Self {
        RouteNode {
            segment,
            is_param: false,
            param_name: None,
            handler: None,
            children: HashMap::new(),
            param_child: None,
            wildcard_child: None,
        }
    }

    fn new_param(param_name: String) -> Self {
        RouteNode {
            segment: format!("{{{}}}", param_name),
            is_param: true,
            param_name: Some(param_name),
            handler: None,
            children: HashMap::new(),
            param_child: None,
            wildcard_child: None,
        }
    }

    fn new_wildcard() -> Self {
        RouteNode {
            segment: "*".to_string(),
            is_param: true,
            param_name: Some("*".to_string()),
            handler: None,
            children: HashMap::new(),
            param_child: None,
            wildcard_child: None,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RouteMatch {
    pub handler_key: String,
    pub params: HashMap<String, String>,
}

impl RadixRouter {
    pub fn new() -> Self {
        RadixRouter {
            root: Arc::new(RouteNode::new("".to_string())),
        }
    }

    /// Add a route to the router
    /// path examples: "/users", "/users/{id}", "/files/*path"
    pub fn add_route(&mut self, _method: &str, path: &str, handler_key: String) -> Result<(), String> {
        if path.is_empty() || !path.starts_with('/') {
            return Err("Path must start with '/'".to_string());
        }

        let segments = self.parse_path(path);
        let current = Arc::clone(&self.root);
        
        // We need to rebuild the tree since Arc<RouteNode> is immutable
        // In a production version, we'd use interior mutability or a different approach
        self.root = Arc::new(self.insert_route(current, &segments, 0, &handler_key)?);
        
        Ok(())
    }

    /// Parse a path into segments, handling parameters and wildcards
    fn parse_path(&self, path: &str) -> Vec<PathSegment> {
        let path = path.trim_start_matches('/');
        if path.is_empty() {
            return vec![PathSegment::Static("".to_string())];
        }

        path.split('/')
            .map(|segment| {
                if segment.starts_with('{') && segment.ends_with('}') {
                    // Parameter: {id} -> id
                    let param_name = segment[1..segment.len()-1].to_string();
                    PathSegment::Param(param_name)
                } else if segment.starts_with('*') {
                    // Wildcard: *path -> path
                    let param_name = if segment.len() > 1 {
                        segment[1..].to_string()
                    } else {
                        "wildcard".to_string()
                    };
                    PathSegment::Wildcard(param_name)
                } else {
                    // Static segment
                    PathSegment::Static(segment.to_string())
                }
            })
            .collect()
    }

    /// Recursively insert a route into the tree
    fn insert_route(
        &self,
        node: Arc<RouteNode>,
        segments: &[PathSegment],
        index: usize,
        handler_key: &str,
    ) -> Result<RouteNode, String> {
        if index >= segments.len() {
            // End of path - set handler
            let mut new_node = (*node).clone();
            new_node.handler = Some(handler_key.to_string());
            return Ok(new_node);
        }

        let segment = &segments[index];
        let mut new_node = (*node).clone();

        match segment {
            PathSegment::Static(name) => {
                if let Some(child) = new_node.children.get(name) {
                    let updated_child = self.insert_route(Arc::clone(child), segments, index + 1, handler_key)?;
                    new_node.children.insert(name.to_owned(), Arc::new(updated_child));
                } else {
                    let mut child = RouteNode::new(name.to_owned());
                    if index + 1 < segments.len() {
                        child = self.insert_route(Arc::new(child), segments, index + 1, handler_key)?;
                    } else {
                        child.handler = Some(handler_key.to_owned());
                    }
                    new_node.children.insert(name.to_owned(), Arc::new(child));
                }
            }
            PathSegment::Param(param_name) => {
                if let Some(param_child) = &new_node.param_child {
                    let updated_child = self.insert_route(Arc::clone(param_child), segments, index + 1, handler_key)?;
                    new_node.param_child = Some(Arc::new(updated_child));
                } else {
                    let mut child = RouteNode::new_param(param_name.clone());
                    if index + 1 < segments.len() {
                        child = self.insert_route(Arc::new(child), segments, index + 1, handler_key)?;
                    } else {
                        child.handler = Some(handler_key.to_string());
                    }
                    new_node.param_child = Some(Arc::new(child));
                }
            }
            PathSegment::Wildcard(param_name) => {
                let mut child = RouteNode::new_wildcard();
                child.param_name = Some(param_name.clone());
                child.handler = Some(handler_key.to_string());
                new_node.wildcard_child = Some(Arc::new(child));
            }
        }

        Ok(new_node)
    }

    /// Find a matching route for the given path
    pub fn find_route(&self, method: &str, path: &str) -> Option<RouteMatch> {
        let path = path.trim_start_matches('/');
        let segments: Vec<&str> = if path.is_empty() {
            vec![]
        } else {
            path.split('/').collect()
        };

        let mut params = HashMap::new();
        if let Some(handler_key) = self.find_handler(&self.root, &segments, 0, &mut params) {
            // Check if the handler matches the method
            if handler_key.starts_with(&format!("{} ", method)) {
                return Some(RouteMatch {
                    handler_key,
                    params,
                });
            }
        }

        None
    }

    /// Recursively find a handler in the tree
    fn find_handler(
        &self,
        node: &RouteNode,
        segments: &[&str],
        index: usize,
        params: &mut HashMap<String, String>,
    ) -> Option<String> {
        if index >= segments.len() {
            // End of path - return handler if exists
            return node.handler.clone();
        }

        let segment = segments[index];

        // Try static match first
        if let Some(child) = node.children.get(segment) {
            if let Some(handler) = self.find_handler(child, segments, index + 1, params) {
                return Some(handler);
            }
        }

        // Try parameter match
        if let Some(param_child) = &node.param_child {
            if let Some(param_name) = &param_child.param_name {
                params.insert(param_name.clone(), segment.to_string());
                if let Some(handler) = self.find_handler(param_child, segments, index + 1, params) {
                    return Some(handler);
                }
                params.remove(param_name);
            }
        }

        // Try wildcard match (matches remaining path)
        if let Some(wildcard_child) = &node.wildcard_child {
            if let Some(param_name) = &wildcard_child.param_name {
                let remaining_path = segments[index..].join("/");
                params.insert(param_name.clone(), remaining_path);
                return wildcard_child.handler.clone();
            }
        }

        None
    }

    /// Get router statistics for debugging
    pub fn stats(&self) -> RouterStats {
        let mut stats = RouterStats::default();
        self.count_nodes(&self.root, &mut stats);
        stats
    }

    fn count_nodes(&self, node: &RouteNode, stats: &mut RouterStats) {
        stats.total_nodes += 1;
        
        if node.handler.is_some() {
            stats.route_count += 1;
        }
        
        if node.is_param {
            stats.param_nodes += 1;
        }

        for child in node.children.values() {
            self.count_nodes(child, stats);
        }

        if let Some(param_child) = &node.param_child {
            self.count_nodes(param_child, stats);
        }

        if let Some(wildcard_child) = &node.wildcard_child {
            self.count_nodes(wildcard_child, stats);
        }
    }
}

#[derive(Debug)]
enum PathSegment {
    Static(String),
    Param(String),
    Wildcard(String),
}

#[derive(Debug, Default)]
pub struct RouterStats {
    pub total_nodes: usize,
    pub route_count: usize,
    pub param_nodes: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_static_routes() {
        let mut router = RadixRouter::new();
        router.add_route("GET", "/users", "GET /users".to_string()).unwrap();
        router.add_route("POST", "/users", "POST /users".to_string()).unwrap();

        let result = router.find_route("GET", "/users");
        assert!(result.is_some());
        assert_eq!(result.unwrap().handler_key, "GET /users");

        let result = router.find_route("POST", "/users");
        assert!(result.is_some());
        assert_eq!(result.unwrap().handler_key, "POST /users");

        let result = router.find_route("DELETE", "/users");
        assert!(result.is_none());
    }

    #[test]
    fn test_param_routes() {
        let mut router = RadixRouter::new();
        router.add_route("GET", "/users/{id}", "GET /users/{id}".to_string()).unwrap();

        let result = router.find_route("GET", "/users/123");
        assert!(result.is_some());
        let route_match = result.unwrap();
        assert_eq!(route_match.handler_key, "GET /users/{id}");
        assert_eq!(route_match.params.get("id"), Some(&"123".to_string()));
    }

    #[test]
    fn test_wildcard_routes() {
        let mut router = RadixRouter::new();
        router.add_route("GET", "/files/*path", "GET /files/*path".to_string()).unwrap();

        let result = router.find_route("GET", "/files/docs/readme.txt");
        assert!(result.is_some());
        let route_match = result.unwrap();
        assert_eq!(route_match.handler_key, "GET /files/*path");
        assert_eq!(route_match.params.get("path"), Some(&"docs/readme.txt".to_string()));
    }

    #[test]
    fn test_complex_routes() {
        let mut router = RadixRouter::new();
        router.add_route("GET", "/api/v1/users/{id}/posts/{post_id}", "GET /api/v1/users/{id}/posts/{post_id}".to_string()).unwrap();

        let result = router.find_route("GET", "/api/v1/users/123/posts/456");
        assert!(result.is_some());
        let route_match = result.unwrap();
        assert_eq!(route_match.params.get("id"), Some(&"123".to_string()));
        assert_eq!(route_match.params.get("post_id"), Some(&"456".to_string()));
    }
}
