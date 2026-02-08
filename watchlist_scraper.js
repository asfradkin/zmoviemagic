// Run this snippet in the browser console on https://www.disneyplus.com/watchlist

(function() {
    const movies = [];
    // Select all anchor tags that likely contain movie links
    // Disney+ specific selectors might change, but looking for links with "entity-" is robust as requested
    const links = document.querySelectorAll('a[href*="/entity-"]');

    links.forEach(link => {
        const href = link.getAttribute('href');
        // Extract ID after "entity-"
        // Example URL: /movies/some-movie-title/1a2b3c4d-5e6f-7g8h-9i0j-k1l2m3n4o5p6
        // or /series/some-series-title/1a2b3c4d-5e6f-7g8h-9i0j-k1l2m3n4o5p6
        // The user specifically mentioned "after the word 'entity-' ".
        // Let's try to capture the ID which is usually the last segment or after "entity-"
        
        // Regex to capture the ID. It seems Disney+ IDs are UUID-like or alphanumeric.
        // Adjusting regex to capture the part after "entity-" which might be part of the path
        // converting "/movies/title/entity-id" -> "id"
        
        // Actually, Disney+ URLs are often like:
        // https://www.disneyplus.com/movies/encanto/33q7t10... 
        // The user said "after the word 'entity-'". 
        // Let's look for that specific pattern first, but also fallback to the last segment if it looks like an ID.
        
        let id = null;
        if (href.includes('entity-')) {
             const parts = href.split('entity-');
             if (parts.length > 1) {
                 id = parts[1].split('/')[0]; // simple extraction
             }
        } else {
            // Fallback: the last part of the URL is often the ID
            const parts = href.split('/');
            const potentialId = parts[parts.length - 1];
            if (potentialId && potentialId.length > 5) {
                id = potentialId;
            }
        }

        // Get title from aria-label or inner text or image alt
        let title = link.getAttribute('aria-label');
        if (!title) {
            const img = link.querySelector('img');
            if (img) {
                title = img.getAttribute('alt');
            }
        }
        if (!title) {
            title = link.innerText;
        }

        if (id && title) {
            // Clean up title
            title = title.trim();
            // Check if we already have this ID (deduplicate)
            if (!movies.find(m => m.id === id)) {
                movies.push({ title, id });
            }
        }
    });

    console.log(`Found ${movies.length} movies.`);
    console.log(JSON.stringify(movies, null, 2));
    
    // Optional: Auto-download
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(movies, null, 2));
    const downloadAnchorNode = document.createElement('a');
    downloadAnchorNode.setAttribute("href",     dataStr);
    downloadAnchorNode.setAttribute("download", "disney_watchlist.json");
    document.body.appendChild(downloadAnchorNode); // required for firefox
    downloadAnchorNode.click();
    downloadAnchorNode.remove();
})();
