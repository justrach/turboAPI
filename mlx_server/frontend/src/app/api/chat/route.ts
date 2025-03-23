import { NextRequest, NextResponse } from 'next/server';

const MLX_API_URL = process.env.MLX_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    
    // Check if this is a streaming request
    const isStream = body.stream === true;
    
    if (!isStream) {
      // Handle regular non-streaming request
      const response = await fetch(`${MLX_API_URL}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        return NextResponse.json(
          { error: 'Failed to get chat completion' },
          { status: response.status }
        );
      }

      const data = await response.json();
      return NextResponse.json(data);
    } else {
      // Handle streaming request
      const response = await fetch(`${MLX_API_URL}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        return NextResponse.json(
          { error: 'Failed to get streaming chat completion' },
          { status: response.status }
        );
      }

      // Create a TransformStream to pipe the response
      const encoder = new TextEncoder();
      const decoder = new TextDecoder();
      
      const transformStream = new TransformStream({
        async transform(chunk, controller) {
          controller.enqueue(encoder.encode(decoder.decode(chunk)));
        },
      });

      // Pipe the response to our transform stream
      response.body?.pipeTo(transformStream.writable);
      
      // Return a streaming response
      return new NextResponse(transformStream.readable, {
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
        },
      });
    }
  } catch (error) {
    console.error('Error in chat completion:', error);
    return NextResponse.json(
      { error: 'Failed to process chat request' },
      { status: 500 }
    );
  }
} 