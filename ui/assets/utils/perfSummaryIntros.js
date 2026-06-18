/**
 * Analiz Asistanı — aylık performans özeti ilk açılış karşılama profilleri (50 adet).
 * Her bot + ay için rastgele biri seçilir ve localStorage'da saklanır.
 */
(function (global) {
    var T = [
        ['Merhaba', 'ben senin analiz asistanınım. Bu ayın performans özetini satır satır aşağıya yazıyorum.'],
        ['Selam', 'analiz asistanın burada — aylık tabloyu okudum, detaylı yorumları sırayla aşağıya bırakıyorum.'],
        ['Merhabalar', 'ben analiz asistanın. Bu ayki kapanışları taradım; çıkarımlarımı aşağıya aktarıyorum.'],
        ['Hoş geldin', 'analiz asistanın hazır. Aylık performans raporunu satır satır aşağıya yazıyorum.'],
        ['Merhaba', 'yine ben, analiz asistanın. Bu ayın özetini senin için aşağıya döküyorum.'],
        ['Selam', 'ben senin analiz asistanınım. Tur verilerini işledim; yorumlarım aşağıda akacak.'],
        ['Merhaba', 'analiz asistanın konuşuyor. Bu ayki performans tablosunu aşağıya taşıyorum.'],
        ['Merhabalar', 'ben senin analiz asistanınım. Aylık raporu okudum, detayları aşağıya yazıyorum.'],
        ['Selam', 'analiz asistanın devrede. Bu ayın kapanışlarını yorumlayıp aşağıya bırakıyorum.'],
        ['Merhaba', 'ben analiz asistanın. Performans özetini hazırladım; metinler aşağıda sırayla geliyor.'],
        ['Hoş geldin', 'ben senin analiz asistanınım. Aylık analizimi satır satır aşağıya aktarıyorum.'],
        ['Merhaba', 'analiz asistanın burada. Bu ayın tur özetini okudum; yorumlarım aşağıda.'],
        ['Selam', 'ben analiz asistanın. Aylık performans değerlendirmemi aşağıya yazıyorum.'],
        ['Merhabalar', 'analiz asistanın hazır. Bu ayki tabloyu senin için aşağıya döküyorum.'],
        ['Merhaba', 'ben senin analiz asistanınım. Kapanış verilerini işledim; analizler aşağıda akıyor.'],
        ['Selam', 'analiz asistanın konuşuyor. Bu ayın performans raporunu aşağıya bırakıyorum.'],
        ['Merhaba', 'yine analiz asistanın. Aylık özeti taradım; çıkarımlarımı aşağıya yazıyorum.'],
        ['Merhabalar', 'ben senin analiz asistanınım. Tur sonuçlarını yorumlayıp aşağıya aktarıyorum.'],
        ['Hoş geldin', 'analiz asistanın burada. Bu ayki performans tablosunu satır satır aşağıya taşıyorum.'],
        ['Merhaba', 'ben analiz asistanın. Aylık raporu hazırladım; detaylı metinler aşağıda.'],
        ['Selam', 'ben senin analiz asistanınım. Bu ayın özetini okudum, yorumlarımı aşağıya yazıyorum.'],
        ['Merhaba', 'analiz asistanın devrede. Performans verilerini işledim; analizler aşağıda sırayla geliyor.'],
        ['Merhabalar', 'ben analiz asistanın. Bu ayki kapanışları değerlendirip aşağıya bırakıyorum.'],
        ['Selam', 'analiz asistanın hazır. Aylık performans özetini aşağıya aktarıyorum.'],
        ['Merhaba', 'ben senin analiz asistanınım. Tur tablosunu taradım; çıkarımlarım aşağıda akacak.'],
        ['Hoş geldin', 'analiz asistanın konuşuyor. Bu ayın raporunu satır satır aşağıya yazıyorum.'],
        ['Merhaba', 'yine ben, analiz asistanın. Aylık performans yorumlarımı aşağıya döküyorum.'],
        ['Selam', 'ben analiz asistanın. Bu ayki verileri okudum; detaylı analizler aşağıda.'],
        ['Merhabalar', 'ben senin analiz asistanınım. Performans özetini hazırladım, aşağıya bırakıyorum.'],
        ['Merhaba', 'analiz asistanın burada. Aylık kapanışları yorumlayıp aşağıya taşıyorum.'],
        ['Selam', 'analiz asistanın devrede. Bu ayın tur özetini aşağıya yazıyorum.'],
        ['Merhaba', 'ben senin analiz asistanınım. Raporu işledim; yorumlarım sırayla aşağıda.'],
        ['Merhabalar', 'analiz asistanın hazır. Bu ayki performans tablosunu aşağıya aktarıyorum.'],
        ['Hoş geldin', 'ben analiz asistanın. Aylık analiz metinlerimi satır satır aşağıya bırakıyorum.'],
        ['Merhaba', 'analiz asistanın konuşuyor. Tur verilerini taradım; çıkarımlarım aşağıda akıyor.'],
        ['Selam', 'ben senin analiz asistanınım. Bu ayın performans değerlendirmesini aşağıya yazıyorum.'],
        ['Merhaba', 'yine analiz asistanın. Aylık özeti okudum; detayları aşağıya döküyorum.'],
        ['Merhabalar', 'ben analiz asistanın. Kapanış sonuçlarını yorumlayıp aşağıya taşıyorum.'],
        ['Selam', 'analiz asistanın burada. Bu ayki raporu hazırladım; metinler aşağıda sırayla geliyor.'],
        ['Merhaba', 'ben senin analiz asistanınım. Performans tablosunu işledim; analizler aşağıda.'],
        ['Hoş geldin', 'analiz asistanın devrede. Aylık tur özetini aşağıya bırakıyorum.'],
        ['Merhaba', 'analiz asistanın hazır. Bu ayın verilerini okudum; yorumlarım aşağıya aktarılıyor.'],
        ['Selam', 'ben analiz asistanın. Aylık performans raporunu satır satır aşağıya yazıyorum.'],
        ['Merhabalar', 'ben senin analiz asistanınım. Bu ayki tabloyu taradım; çıkarımlarım aşağıda.'],
        ['Merhaba', 'analiz asistanın konuşuyor. Tur kapanışlarını değerlendirip aşağıya döküyorum.'],
        ['Selam', 'ben senin analiz asistanınım. Aylık özet hazır; detaylı metinler aşağıda akacak.'],
        ['Merhaba', 'yine analiz asistanın. Bu ayın performans yorumlarını aşağıya taşıyorum.'],
        ['Merhabalar', 'analiz asistanın burada. Raporu okudum; analizlerimi aşağıya yazıyorum.'],
        ['Hoş geldin', 'ben analiz asistanın. Bu ayki kapanışları işledim; yorumlarım sırayla aşağıda.'],
        ['Merhaba', 'ben senin analiz asistanınım. Aylık performans tablosunu aşağıya bırakıyorum — okumaya hazır ol.']
    ];

    global.PERF_SUMMARY_FIRST_INTROS = T.map(function (row) {
        return function (name) {
            var g = name ? (row[0] + ' ' + name) : row[0];
            return g + ', ' + row[1];
        };
    });
})(typeof window !== 'undefined' ? window : global);
