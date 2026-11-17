import type { Metadata } from "next";
import { IBM_Plex_Sans, Newsreader } from "next/font/google";

import { Providers } from "@/components/providers";
import { ModeBand, SiteFooter, SiteHeader } from "@/components/site-chrome";

import "./globals.css";

const plex = IBM_Plex_Sans({ variable: "--font-plex", subsets: ["latin"], weight: ["400", "500", "600"] });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], weight: ["400", "500"], style: ["normal", "italic"] });

export const metadata: Metadata = {
  title: { default: "ShockTrace", template: "%s · ShockTrace" },
  description:
    "Open-source econometric forecasting: do weather anomalies improve out-of-sample prediction of food-price changes and spikes?",
};

// Applies the saved theme before paint to avoid a light/dark flash.
const themeScript = `try{var t=localStorage.getItem('st-theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${plex.variable} ${newsreader.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="flex min-h-screen flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
          Skip to content
        </a>
        <Providers>
          <SiteHeader />
          <ModeBand />
          <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 pt-8 md:px-6 md:pt-12">
            {children}
          </main>
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}
