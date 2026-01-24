<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="2.0" 
                xmlns:html="http://www.w3.org/TR/REC-html40"
                xmlns:sitemap="http://www.sitemaps.org/schemas/sitemap/0.9"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" version="1.0" encoding="UTF-8" indent="yes"/>
  <xsl:template match="/">
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head>
        <title>XML Sitemap - Sport Daily</title>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <style type="text/css">
          body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
            color: #333;
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 20px;
            background: #f9fafb;
          }
          .header {
            padding-bottom: 20px;
            border-bottom: 2px solid #e5e7eb;
            margin-bottom: 30px;
          }
          h1 {
            color: #1f2937;
            font-size: 28px;
            margin: 0;
          }
          p.desc {
            color: #6b7280;
            font-size: 14px;
            margin-top: 10px;
          }
          table {
            border-collapse: collapse;
            width: 100%;
            background: #fff;
            box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
            border-radius: 8px;
            overflow: hidden;
          }
          th {
            background-color: #f3f4f6;
            text-align: left;
            padding: 15px 20px;
            font-size: 12px;
            text-transform: uppercase;
            color: #6b7280;
            font-weight: 700;
            letter-spacing: 0.05em;
            border-bottom: 1px solid #e5e7eb;
          }
          td {
            padding: 15px 20px;
            border-bottom: 1px solid #e5e7eb;
            font-size: 14px;
            color: #374151;
          }
          tr:hover td {
            background-color: #f9fafb;
          }
          a {
            color: #dc2626; /* News Red */
            text-decoration: none;
            font-weight: 500;
          }
          a:hover {
            text-decoration: underline;
          }
          .count {
            float: right;
            background: #e5e7eb;
            padding: 2px 10px;
            border-radius: 99px;
            font-size: 12px;
            font-weight: bold;
          }
        </style>
      </head>
      <body>
        <div class="header">
          <h1>XML Sitemap</h1>
          <p class="desc">
            This is a generated XML Sitemap for <strong>Sport Daily</strong>. It helps search engines like Google to index our content.
            <span class="count"><xsl:value-of select="count(sitemap:urlset/sitemap:url)"/> URLs Found</span>
          </p>
        </div>
        <table>
          <thead>
            <tr>
              <th width="70%">URL Location</th>
              <th width="30%">Last Modified</th>
            </tr>
          </thead>
          <tbody>
            <xsl:for-each select="sitemap:urlset/sitemap:url">
              <tr>
                <td>
                  <a href="{sitemap:loc}"><xsl:value-of select="sitemap:loc"/></a>
                </td>
                <td>
                  <xsl:value-of select="concat(substring(sitemap:lastmod,0,11),concat(' ', substring(sitemap:lastmod,12,5)))"/>
                </td>
              </tr>
            </xsl:for-each>
          </tbody>
        </table>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
