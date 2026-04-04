import { Component, ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  inline?: boolean;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught error:", error, errorInfo);
  }

  public reset() {
    this.setState({ hasError: false, error: null });
  }

  public render() {
    if (this.state.hasError) {
      // Custom fallback provided by parent
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Inline mode: compact error within component space
      if (this.props.inline) {
        return (
          <div className="flex flex-col items-center justify-center p-6 text-center space-y-2 border border-border/50 rounded-xl bg-card/50">
            <p className="text-sm font-medium text-destructive">Component failed to render</p>
            <p className="text-xs text-muted-foreground max-w-xs truncate">
              {this.state.error?.message || "An unexpected error occurred"}
            </p>
            <button
              onClick={() => this.reset()}
              className="text-xs px-3 py-1 rounded-md bg-muted hover:bg-muted/80 transition-colors"
            >
              Try Again
            </button>
          </div>
        );
      }

      // Full-page mode (default): overlay error for critical failures
      return (
        <div className="min-h-screen flex items-center justify-center bg-background text-foreground p-8">
          <div className="max-w-md w-full bg-card border border-border rounded-xl p-6 space-y-4">
            <h1 className="text-2xl font-bold text-destructive">Oops! Something went wrong</h1>
            <p className="text-sm text-muted-foreground">
              {this.state.error?.message || "An unexpected error occurred"}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="w-full px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              Reload Page
            </button>
            <details className="text-xs font-mono text-muted-foreground">
              <summary className="cursor-pointer">Error Details</summary>
              <pre className="mt-2 p-2 bg-muted rounded overflow-auto max-h-64">
                {this.state.error?.toString()}
              </pre>
            </details>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
