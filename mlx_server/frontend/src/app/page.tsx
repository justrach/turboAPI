"use client";

import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { ArrowUp, Loader2, MessageSquare } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ThemeToggle } from "@/components/theme-toggle";
import { ThinkingView } from "@/components/thinking-view";

interface Message {
  role: "user" | "assistant";
  content: string;
  id: string;
  thinking?: string;
}

interface Model {
  id: string;
  object: string;
  created: number;
  owned_by: string;
}

export default function Home() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [models, setModels] = useState<Model[]>([]);
  const [selectedModel, setSelectedModel] = useState("qwq");
  const [streamingContent, setStreamingContent] = useState("");
  const [rawResponse, setRawResponse] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Check if current model is qwq (thinking model)
  const isQwqModel = selectedModel === "qwq";

  useEffect(() => {
    // Fetch available models using server-side API route
    const fetchModels = async () => {
      try {
        const res = await fetch("/api/models");
        if (!res.ok) {
          throw new Error(`Failed to fetch models: ${res.status}`);
        }
        const data = await res.json();
        setModels(data.data);
        
        // Set default model if available
        if (data.data.length > 0) {
          setSelectedModel(data.data[0].id);
        }
      } catch (error) {
        console.error("Error fetching models:", error);
      }
    };

    fetchModels();
  }, []);

  useEffect(() => {
    // Scroll to bottom when messages change
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!input.trim()) return;
    
    // Add user message with a unique ID
    const userMessage: Message = { 
      role: "user", 
      content: input, 
      id: `user-${Date.now()}` 
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    // Reset streaming content and raw response
    setStreamingContent("");
    setRawResponse("");

    try {
      // Use server-side API route for chat completions
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: selectedModel,
          messages: [...messages, userMessage].map(({ role, content }) => ({ role, content })),
          max_tokens: 8192,
          stream: true, // Enable streaming
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // Handle streaming response
      const reader = response.body?.getReader();
      
      if (reader) {
        let done = false;
        let partialLine = "";
        let currentContent = "";
        
        while (!done) {
          const { value, done: readerDone } = await reader.read();
          done = readerDone;
          
          if (value) {
            // Convert the Uint8Array to a string
            const chunk = new TextDecoder("utf-8").decode(value);
            
            // Process chunk line by line
            const lines = (partialLine + chunk).split("\n");
            partialLine = lines.pop() || "";
            
            for (const line of lines) {
              if (line.startsWith("data: ") && line !== "data: [DONE]") {
                try {
                  const data = JSON.parse(line.substring(6));
                  
                  if (data.choices && data.choices.length > 0) {
                    const delta = data.choices[0].delta;
                    
                    if (delta && delta.content) {
                      currentContent += delta.content;
                      
                      // For qwq model, store the raw response for thinking view
                      if (isQwqModel) {
                        setRawResponse(currentContent);
                      }
                      
                      // Show the clean content in the streaming message
                      setStreamingContent(currentContent);
                    }
                  }
                } catch (error) {
                  console.error("Error parsing JSON:", error);
                }
              }
            }
          }
        }
        
        // When stream is complete, add the full message with a unique ID
        if (currentContent) {
          // For QWQ model, store the response in thinking field, but keep the content too
          // so the ThinkingView can properly extract the response part
          setMessages((prev) => [
            ...prev,
            { 
              role: "assistant", 
              content: currentContent,  // Keep content for all models
              thinking: isQwqModel ? currentContent : undefined, // For QWQ, duplicate in thinking field
              id: `assistant-${Date.now()}`
            },
          ]);
          
          // Reset streaming content
          setStreamingContent("");
          setRawResponse("");
        }
      }
    } catch (error) {
      console.error("Error sending message:", error);
      // Add error message with a unique ID
      setMessages((prev) => [
        ...prev,
        { 
          role: "assistant", 
          content: "Sorry, there was an error processing your request.",
          id: `error-${Date.now()}`
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Header with model selection */}
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container max-w-4xl mx-auto flex h-14 items-center justify-between">
          <div className="flex items-center space-x-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            <h1 className="text-lg font-semibold">MLX Chat</h1>
          </div>
          
          <div className="flex items-center gap-2">
            <Select
              value={selectedModel}
              onValueChange={setSelectedModel}
              disabled={isLoading}
            >
              <SelectTrigger className="w-[180px] rounded-xl">
                <SelectValue placeholder="Select model" />
              </SelectTrigger>
              <SelectContent className="rounded-xl">
                {models.map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* Chat area - restructured for edge-to-edge scrollbar */}
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto scrollbar-thin scrollbar-thumb-primary/20 scrollbar-track-transparent hover:scrollbar-thumb-primary/40">
          <div className="container max-w-4xl mx-auto p-4">
            <div className="space-y-4 pb-20">
              {messages.length === 0 && !streamingContent ? (
                <div className="flex flex-col items-center justify-center h-[70vh] text-center space-y-4">
                  <div className="flex flex-col items-center space-y-2">
                    <div className="rounded-full bg-primary/10 p-4">
                      <MessageSquare className="h-6 w-6 text-primary" />
                    </div>
                    <h2 className="text-xl font-bold">Start a conversation</h2>
                  </div>
                  <p className="text-muted-foreground max-w-md">
                    Send a message to start chatting with the selected MLX model.
                  </p>
                </div>
              ) : (
                <>
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className={`flex flex-col ${
                        message.role === "user" ? "items-end" : "items-start"
                      }`}
                    >
                      {/* Message bubble - only shown for user messages or non-qwq model responses */}
                      {(message.role === "user" || (message.role === "assistant" && !isQwqModel)) && (
                        <div
                          className={`max-w-[80%] rounded-xl p-4 message-animate ${
                            message.role === "user"
                              ? "bg-primary text-primary-foreground"
                              : "bg-muted"
                          }`}
                        >
                          <p className="whitespace-pre-wrap">{message.content}</p>
                        </div>
                      )}
                      
                      {/* Thinking UI for QWQ model responses */}
                      {message.role === "assistant" && isQwqModel && (
                        <div className="max-w-[80%]">
                          <ThinkingView 
                            thinkingContent={message.content} 
                            isVisible={true} 
                          />
                        </div>
                      )}
                    </div>
                  ))}
                  
                  {/* Streaming message - only shown for non-qwq models */}
                  {streamingContent && !isQwqModel && (
                    <div className="flex justify-start">
                      <div className="max-w-[80%] rounded-xl p-4 bg-muted message-animate">
                        <p className="whitespace-pre-wrap">
                          {streamingContent}
                          <span className="inline-block w-2 h-4 ml-1 bg-primary animate-pulse"></span>
                        </p>
                      </div>
                    </div>
                  )}
                  
                  {/* QWQ model streaming - show thinking UI */}
                  {rawResponse && isQwqModel && (
                    <div className="flex justify-start">
                      <div className="max-w-[80%]">
                        <ThinkingView 
                          thinkingContent={rawResponse} 
                          isVisible={true} 
                        />
                      </div>
                    </div>
                  )}
                </>
              )}
              <div ref={messagesEndRef} />
            </div>
          </div>
        </div>
      </div>

      {/* Input area */}
      <div className="sticky bottom-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-t p-4">
        <form onSubmit={handleSubmit} className="container max-w-4xl mx-auto">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Type your message..."
                className="w-full rounded-xl border bg-background px-4 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
                disabled={isLoading}
              />
            </div>
            <Button type="submit" className="rounded-xl" disabled={isLoading || !input.trim()}>
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowUp className="h-4 w-4" />
              )}
              <span className="sr-only">Send</span>
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
