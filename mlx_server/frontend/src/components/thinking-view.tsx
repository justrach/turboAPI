"use client";

import React from "react";
import { Brain } from "lucide-react";
import { 
  Accordion, 
  AccordionContent, 
  AccordionItem, 
  AccordionTrigger 
} from "@/components/ui/accordion";
import ReactMarkdown from 'react-markdown';

interface ThinkingViewProps {
  thinkingContent: string;
  isVisible: boolean;
}

export function ThinkingView({ thinkingContent, isVisible }: ThinkingViewProps) {
  if (!isVisible || !thinkingContent) return null;
  
  // Parse content based on </think> tag
  const parts = thinkingContent.split("</think>");
  const hasThinkTag = parts.length > 1;
  
  let thinking = "";
  let response = "";
  
  if (hasThinkTag) {
    thinking = parts[0].trim();
    response = parts[1].trim();
  } else {
    // Fallback to previous logic if </think> tag isn't found
    const hasReasoningContent = thinkingContent.includes("Okay, the user") || 
                                thinkingContent.includes("I should") ||
                                thinkingContent.includes("Let me");
    
    thinking = thinkingContent;
    
    if (hasReasoningContent) {
      const paragraphs = thinkingContent.split("\n\n");
      if (paragraphs.length > 1) {
        response = paragraphs[paragraphs.length - 1].trim();
      } else {
        const sentences = thinkingContent.split(". ");
        if (sentences.length > 1) {
          response = sentences[sentences.length - 1].trim();
        }
      }
    }
  }
  
  // Always show the response if we have one (from any parsing method)
  const shouldShowResponse = response.length > 0;
  
  return (
    <>
      {/* Show response when we have one - add a debug class to see it */}
      {shouldShowResponse && (
        <div className="whitespace-pre-wrap prose prose-sm dark:prose-invert max-w-none p-4 bg-muted rounded-xl">
          <ReactMarkdown>{response}</ReactMarkdown>
        </div>
      )}
      
      {/* Always show thinking content in the accordion */}
      <Accordion type="single" collapsible className="w-full mt-2">
        <AccordionItem value="thinking" className="border-b-0">
          <AccordionTrigger className="py-1 text-sm font-medium text-primary">
            <div className="flex items-center gap-2">
              <Brain className="h-4 w-4" />
              <span>View thinking process</span>
            </div>
          </AccordionTrigger>
          <AccordionContent>
            <div className="mt-1 bg-muted/50 rounded-lg p-3 text-xs font-mono whitespace-pre-wrap overflow-auto max-h-[400px] text-muted-foreground
              scrollbar-thin scrollbar-thumb-primary/40 scrollbar-track-transparent hover:scrollbar-thumb-primary/60">
              {thinking}
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </>
  );
} 